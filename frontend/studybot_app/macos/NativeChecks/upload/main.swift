import Foundation
let fm = FileManager.default
func tmp(_ n: String) -> URL { fm.temporaryDirectory.appendingPathComponent("sb-\(n)-\(UUID().uuidString)") }
let userDir = tmp("user"), staging = tmp("staging"), elsewhere = tmp("elsewhere")
try fm.createDirectory(at: userDir, withIntermediateDirectories: true)
try fm.createDirectory(at: elsewhere, withIntermediateDirectories: true)
let pdfBytes = Data("%PDF-1.4\n%fake but with a PDF header\n".utf8)
let original = userDir.appendingPathComponent("My Lecture.pdf")
try pdfBytes.write(to: original)
try Data("plain".utf8).write(to: userDir.appendingPathComponent("notes.txt"))
try Data("not really a pdf".utf8).write(to: userDir.appendingPathComponent("fake.pdf"))
try fm.createDirectory(at: userDir.appendingPathComponent("folder.pdf"), withIntermediateDirectories: true)
try fm.createSymbolicLink(at: userDir.appendingPathComponent("link.pdf"), withDestinationURL: original)
let originalAttrs = try fm.attributesOfItem(atPath: original.path)
defer { for u in [userDir, staging, elsewhere] { try? fm.removeItem(at: u) } }
var failures = 0
func check(_ name: String, _ ok: Bool) { print(ok ? "PASS" : "FAIL", name); if !ok { failures += 1 } }
func fails(_ url: URL, _ want: String, _ auth: FolderAuthorization) -> Bool {
  do { _ = try auth.stageUpload(selected: url, stagingDirectory: staging.path); return false }
  catch let e as AuthorizationFailure { return "\(e)" == want } catch { return false }
}
func stagedCount() -> Int { (try? fm.contentsOfDirectory(atPath: staging.path).count) ?? 0 }

let auth = FolderAuthorization()  // note: no folder lease is needed for a direct upload
let staged = try auth.stageUpload(selected: original, stagingDirectory: staging.path)
let copy = staging.appendingPathComponent("\(staged.stagingId).pdf")
check("display name is the original filename", staged.displayName == "My Lecture.pdf")
check("size matches", staged.sizeBytes == pdfBytes.count)
check("staging id is a lowercase uuid", UUID(uuidString: staged.stagingId) != nil && staged.stagingId == staged.stagingId.lowercased())
check("copy has identical bytes", (try? Data(contentsOf: copy)) == pdfBytes)
check("copy is private (0600)", ((try? fm.attributesOfItem(atPath: copy.path)[.posixPermissions] as? Int) ?? 0) == 0o600)
check("staging dir is private (0700)", ((try? fm.attributesOfItem(atPath: staging.path)[.posixPermissions] as? Int) ?? 0) == 0o700)
let afterAttrs = try fm.attributesOfItem(atPath: original.path)
check("original unchanged (bytes, mtime, size)", (try? Data(contentsOf: original)) == pdfBytes
  && (afterAttrs[.modificationDate] as? Date) == (originalAttrs[.modificationDate] as? Date)
  && (afterAttrs[.size] as? Int) == (originalAttrs[.size] as? Int))
check("original not renamed or moved", fm.fileExists(atPath: original.path))
check("a file from any other location works", (try? auth.stageUpload(selected: {
  let p = elsewhere.appendingPathComponent("elsewhere.PDF"); try? pdfBytes.write(to: p); return p }(), stagingDirectory: staging.path))?.displayName == "elsewhere.PDF")
check("symlink to a PDF stages the target bytes", (try? auth.stageUpload(selected: userDir.appendingPathComponent("link.pdf"), stagingDirectory: staging.path))?.sizeBytes == pdfBytes.count)
let before = stagedCount()
check("non-pdf extension rejected", fails(userDir.appendingPathComponent("notes.txt"), "notPdf", auth))
check(".pdf without PDF header rejected", fails(userDir.appendingPathComponent("fake.pdf"), "notPdf", auth))
check("directory rejected", fails(userDir.appendingPathComponent("folder.pdf"), "notPdf", auth))
check("missing file rejected", fails(userDir.appendingPathComponent("missing.pdf"), "notPdf", auth))
check("rejections stage nothing", stagedCount() == before)
// failure while copying leaves nothing behind
let blocker = tmp("blocker"); try Data("file".utf8).write(to: blocker)
defer { try? fm.removeItem(at: blocker) }
do { _ = try auth.stageUpload(selected: original, stagingDirectory: blocker.appendingPathComponent("sub").path); check("copy failure reports staging_failed", false) }
catch let e as AuthorizationFailure { check("copy failure reports staging_failed", "\(e)" == "stagingFailed") } catch { check("copy failure reports staging_failed", false) }
check("original still unchanged after failures", (try? Data(contentsOf: original)) == pdfBytes)
print(failures == 0 ? "ALL PASS" : "FAILURES: \(failures)")
exit(failures == 0 ? 0 : 1)
