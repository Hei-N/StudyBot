import Foundation
let fm = FileManager.default
func tmp(_ n: String) -> URL { fm.temporaryDirectory.appendingPathComponent("sb-\(n)-\(UUID().uuidString)") }
let userDir = tmp("user"), staging = tmp("staging")
try fm.createDirectory(at: userDir, withIntermediateDirectories: true)
let pdfBytes = Data("%PDF-1.4\n%fake but with a PDF header\n".utf8)
func write(_ name: String, _ data: Data) -> URL { let u = userDir.appendingPathComponent(name); try! data.write(to: u); return u }
let originals = (1...7).map { write("doc\($0).pdf", pdfBytes) }
let text = write("notes.txt", Data("plain".utf8)), fakePdf = write("fake.pdf", Data("not a pdf".utf8))
let image = write("photo.png", Data([0x89, 0x50, 0x4E, 0x47]))
let folder = userDir.appendingPathComponent("a-folder.pdf"); try fm.createDirectory(at: folder, withIntermediateDirectories: true)
defer { try? fm.removeItem(at: userDir); try? fm.removeItem(at: staging) }
var failures = 0
func check(_ name: String, _ ok: Bool) { print(ok ? "PASS" : "FAIL", name); if !ok { failures += 1 } }
func count() -> Int { (try? fm.contentsOfDirectory(atPath: staging.path).count) ?? 0 }
let auth = FolderAuthorization()

check("one valid PDF is a valid drag", DroppedFiles.containsPdf([originals[0]]))
check("a PDF among other files is a valid drag", DroppedFiles.containsPdf([text, originals[0], image]))
check("text and images are not a valid drag", !DroppedFiles.containsPdf([text, image]))
check("a folder is not a valid drag", !DroppedFiles.containsPdf([folder]))
check("nothing dropped is not a valid drag", !DroppedFiles.containsPdf([]))

let one = DroppedFiles.stage([originals[0]], stagingDirectory: staging.path, using: auth)
check("one PDF is staged", one.count == 1 && one[0].errorCode == nil && one[0].stagingId != nil && one[0].displayName == "doc1.pdf")
check("the staged copy is private and identical", one[0].stagingId.flatMap { try? Data(contentsOf: staging.appendingPathComponent("\($0).pdf")) } == pdfBytes)
let mixed = DroppedFiles.stage([originals[1], text, image, fakePdf, folder], stagingDirectory: staging.path, using: auth)
check("a PDF is accepted next to rejected files", mixed[0].errorCode == nil)
check("text, image, fake PDF and folder are each rejected with a code", mixed[1...].allSatisfy { $0.errorCode == "not_pdf" && $0.stagingId == nil })
let before = count()
let many = DroppedFiles.stage(originals, stagingDirectory: staging.path, using: auth)
check("only five files are staged from a larger drop", many.filter { $0.errorCode == nil }.count == 5 && many[5...].allSatisfy { $0.errorCode == "too_many" })
check("rejected and extra files stage nothing", count() == before + 5)
check("every original is unchanged", originals.allSatisfy { (try? Data(contentsOf: $0)) == pdfBytes })
check("items carry no path", mixed.allSatisfy { $0.dictionary.values.allSatisfy { !(($0 as? String)?.contains(userDir.path) ?? false) } })
print(failures == 0 ? "ALL PASS" : "FAILURES: \(failures)")
exit(failures == 0 ? 0 : 1)
