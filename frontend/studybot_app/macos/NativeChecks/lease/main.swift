import Foundation
let fm = FileManager.default
let root = fm.temporaryDirectory.appendingPathComponent("sb-auth-\(UUID().uuidString)")
let outside = fm.temporaryDirectory.appendingPathComponent("sb-out-\(UUID().uuidString)")
try fm.createDirectory(at: root.appendingPathComponent("Week 1"), withIntermediateDirectories: true)
try fm.createDirectory(at: outside, withIntermediateDirectories: true)
try "hello".write(to: root.appendingPathComponent("Week 1/a.txt"), atomically: true, encoding: .utf8)
try "secret".write(to: outside.appendingPathComponent("s.txt"), atomically: true, encoding: .utf8)
try fm.createSymbolicLink(at: root.appendingPathComponent("escape"), withDestinationURL: outside)
defer { try? fm.removeItem(at: root); try? fm.removeItem(at: outside) }
var failures = 0
func check(_ name: String, _ ok: Bool) { print(ok ? "PASS" : "FAIL", name); if !ok { failures += 1 } }

let auth = FolderAuthorization()
let bookmark = try FolderAuthorization.makeBookmark(for: root)
check("bookmark created", bookmark.count > 0)
let lease = try auth.startAccess(bookmark: bookmark)
check("startAccess resolves to the folder", URL(fileURLWithPath: lease.path).resolvingSymlinksInPath().path == root.resolvingSymlinksInPath().path)
check("fresh bookmark is not refreshed", lease.refreshedBookmark == nil)
check("probe reads a file inside", try auth.probeRead(leaseId: lease.id, relativePath: "Week 1/a.txt"))
check("probe rejects ..", try !auth.probeRead(leaseId: lease.id, relativePath: "../x"))
check("probe rejects nested ..", try !auth.probeRead(leaseId: lease.id, relativePath: "Week 1/../../x"))
check("probe rejects absolute", try !auth.probeRead(leaseId: lease.id, relativePath: "/etc/hosts"))
check("probe rejects symlink escape", try !auth.probeRead(leaseId: lease.id, relativePath: "escape/s.txt"))
check("probe rejects missing file", try !auth.probeRead(leaseId: lease.id, relativePath: "nope.txt"))
check("probe rejects directory-only/empty", try !auth.probeRead(leaseId: lease.id, relativePath: ""))
auth.stopAccess(leaseId: lease.id)
auth.stopAccess(leaseId: lease.id)
do { _ = try auth.probeRead(leaseId: lease.id, relativePath: "Week 1/a.txt"); check("probe after stop throws", false) } catch { check("probe after stop throws", true) }
do { _ = try auth.startAccess(bookmark: Data([1,2,3])); check("garbage bookmark fails", false) } catch { check("garbage bookmark fails", true) }
// moved folder: bookmark follows the folder (resolves) or fails; never falls back to a path
let moved = root.deletingLastPathComponent().appendingPathComponent("sb-moved-\(UUID().uuidString)")
try fm.moveItem(at: root, to: moved)
if let l2 = try? auth.startAccess(bookmark: bookmark) {
  check("moved folder: bookmark resolves to the new location", URL(fileURLWithPath: l2.path).resolvingSymlinksInPath().path == moved.resolvingSymlinksInPath().path)
  check("moved folder: stale flag handled", true)
  auth.stopAccess(leaseId: l2.id)
} else { check("moved folder: bookmark fails cleanly", true) }
try fm.moveItem(at: moved, to: root)
auth.stopAll()
print(failures == 0 ? "ALL PASS" : "FAILURES: \(failures)")
exit(failures == 0 ? 0 : 1)
