import Foundation
let fm = FileManager.default
func tmp(_ n: String) -> URL { fm.temporaryDirectory.appendingPathComponent("sb-\(n)-\(UUID().uuidString)") }
let root = tmp("root"), outside = tmp("out"), staging = tmp("staging")
try fm.createDirectory(at: root.appendingPathComponent("Week 2"), withIntermediateDirectories: true)
try fm.createDirectory(at: outside, withIntermediateDirectories: true)
let pdfBytes = Data("%PDF-1.4\n%fake but with a PDF header\n".utf8)
try pdfBytes.write(to: root.appendingPathComponent("Week 2/Lecture.pdf"))
try pdfBytes.write(to: root.appendingPathComponent("top.PDF"))
try Data("plain".utf8).write(to: root.appendingPathComponent("notes.txt"))
try Data("not really a pdf".utf8).write(to: root.appendingPathComponent("fake.pdf"))
try pdfBytes.write(to: outside.appendingPathComponent("secret.pdf"))
try fm.createSymbolicLink(at: root.appendingPathComponent("escape.pdf"), withDestinationURL: outside.appendingPathComponent("secret.pdf"))
try fm.createSymbolicLink(at: root.appendingPathComponent("linkdir"), withDestinationURL: outside)
try fm.createSymbolicLink(at: root.appendingPathComponent("inside-link.pdf"), withDestinationURL: root.appendingPathComponent("Week 2/Lecture.pdf"))
try fm.createDirectory(at: root.appendingPathComponent("folder.pdf"), withIntermediateDirectories: true)
defer { for u in [root, outside, staging] { try? fm.removeItem(at: u) } }
var failures = 0
func check(_ name: String, _ ok: Bool) { print(ok ? "PASS" : "FAIL", name); if !ok { failures += 1 } }
func fails(_ url: URL, _ want: String, _ auth: FolderAuthorization, _ lease: String) -> Bool {
  do { _ = try auth.stagePdf(selected: url, leaseId: lease, stagingDirectory: staging.path); return false }
  catch let e as AuthorizationFailure { return "\(e)" == want } catch { return false }
}
let auth = FolderAuthorization()
let lease = try auth.startAccess(bookmark: try FolderAuthorization.makeBookmark(for: root))
let staged = try auth.stagePdf(selected: root.appendingPathComponent("Week 2/Lecture.pdf"), leaseId: lease.id, stagingDirectory: staging.path)
check("staged relative path", staged.relativePath == "Week 2/Lecture.pdf")
check("display name and size", staged.displayName == "Lecture.pdf" && staged.sizeBytes == pdfBytes.count)
let copy = staging.appendingPathComponent("\(staged.stagingId).pdf")
check("staging id is a lowercase uuid", UUID(uuidString: staged.stagingId) != nil && staged.stagingId == staged.stagingId.lowercased())
check("staged copy exists with identical bytes", (try? Data(contentsOf: copy)) == pdfBytes)
let perms = (try? fm.attributesOfItem(atPath: copy.path)[.posixPermissions] as? Int) ?? 0
check("staged copy is private (0600)", perms == 0o600)
check("staging dir is private (0700)", ((try? fm.attributesOfItem(atPath: staging.path)[.posixPermissions] as? Int) ?? 0) == 0o700)
check("source unchanged", (try? Data(contentsOf: root.appendingPathComponent("Week 2/Lecture.pdf"))) == pdfBytes)
check("uppercase .PDF accepted", (try? auth.stagePdf(selected: root.appendingPathComponent("top.PDF"), leaseId: lease.id, stagingDirectory: staging.path))?.relativePath == "top.PDF")
check("file outside the source rejected", fails(outside.appendingPathComponent("secret.pdf"), "outsideSource", auth, lease.id))
check("symlink escaping the source rejected", fails(root.appendingPathComponent("escape.pdf"), "outsideSource", auth, lease.id))
check("file via a symlinked folder rejected", fails(root.appendingPathComponent("linkdir/secret.pdf"), "outsideSource", auth, lease.id))
check("symlink to a file inside the source resolves inside", (try? auth.stagePdf(selected: root.appendingPathComponent("inside-link.pdf"), leaseId: lease.id, stagingDirectory: staging.path))?.relativePath == "Week 2/Lecture.pdf")
check("non-pdf extension rejected", fails(root.appendingPathComponent("notes.txt"), "notPdf", auth, lease.id))
check(".pdf without PDF header rejected", fails(root.appendingPathComponent("fake.pdf"), "notPdf", auth, lease.id))
check("directory rejected", fails(root.appendingPathComponent("folder.pdf"), "notPdf", auth, lease.id))
check("the source root itself rejected", fails(root, "outsideSource", auth, lease.id))
check("unknown lease rejected", fails(root.appendingPathComponent("top.PDF"), "unknownLease", auth, "nope"))
let before = (try? fm.contentsOfDirectory(atPath: staging.path).count) ?? -1
_ = fails(outside.appendingPathComponent("secret.pdf"), "outsideSource", auth, lease.id)
check("rejections stage nothing", ((try? fm.contentsOfDirectory(atPath: staging.path).count) ?? -2) == before)
auth.stopAll()
print(failures == 0 ? "ALL PASS" : "FAILURES: \(failures)")
exit(failures == 0 ? 0 : 1)
