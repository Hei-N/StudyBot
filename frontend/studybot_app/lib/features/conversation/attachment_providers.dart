import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/models/message.dart';
import '../../core/platform/file_drop.dart';
import '../../core/platform/folder_authorization.dart';
import '../connection/connection_providers.dart';
import '../library/library_providers.dart';

/// Most PDFs that can be attached to one message (matches the engine's limit).
const maxChatAttachments = 5;

enum AttachmentStatus { uploading, ready, failed }

/// A file in the composer before it is sent. [fileId] is StudyBot's id for the processed file.
class PendingAttachment {
  const PendingAttachment({
    required this.localId,
    required this.displayName,
    required this.status,
    this.fileId,
    this.pageCount,
    this.textPageCount,
    this.failure,
  });

  final int localId;
  final String displayName;
  final AttachmentStatus status;
  final String? fileId;
  final int? pageCount;
  final int? textPageCount;

  /// A short, user-facing reason when [status] is failed.
  final String? failure;

  PendingAttachment copyWith({
    AttachmentStatus? status,
    String? fileId,
    int? pageCount,
    int? textPageCount,
    String? failure,
  }) {
    return PendingAttachment(
      localId: localId,
      displayName: displayName,
      status: status ?? this.status,
      fileId: fileId ?? this.fileId,
      pageCount: pageCount ?? this.pageCount,
      textPageCount: textPageCount ?? this.textPageCount,
      failure: failure ?? this.failure,
    );
  }

  /// What the message bubble shows for this file right after sending.
  MessageAttachment toMessageAttachment() => MessageAttachment(
    id: -localId,
    fileId: fileId!,
    displayName: displayName,
    pageCount: pageCount,
    textPageCount: textPageCount,
    processingState: 'ready',
  );
}

String _failureText(String? code) => switch (code) {
  'password_required' => 'Password protected',
  'invalid_pdf' => 'Not a valid PDF',
  'file_too_large' ||
  'too_many_pages' ||
  'text_too_large' ||
  'too_large' => 'Too large',
  'not_pdf' => 'Not a PDF',
  _ => 'Upload failed',
};

String _failureNotice(String? code) => switch (code) {
  'password_required' => 'This PDF is password protected.',
  'invalid_pdf' => 'This file is not a valid PDF.',
  'file_too_large' ||
  'too_many_pages' ||
  'text_too_large' ||
  'too_large' => 'This PDF is too large to import.',
  'not_pdf' => 'Please choose a PDF file.',
  'too_many' => 'You can attach up to $maxChatAttachments PDFs to one message.',
  _ => "Couldn't attach that file. Please try again.",
};

/// Pending attachments, kept per chat so switching chats never moves a file to another chat.
/// Uploading uses the same pipeline as the Study Library upload (private copy, text extraction),
/// but the file is not added to the library.
class ComposerAttachments
    extends Notifier<Map<String, List<PendingAttachment>>> {
  int _nextLocalId = 1;

  @override
  Map<String, List<PendingAttachment>> build() => const {};

  List<PendingAttachment> of(String chatId) => state[chatId] ?? const [];

  void _put(String chatId, List<PendingAttachment> items) {
    final next = {...state};
    if (items.isEmpty) {
      next.remove(chatId);
    } else {
      next[chatId] = items;
    }
    state = next;
  }

  void _notice(String message) =>
      ref.read(attachmentNoticeProvider.notifier).set(message);

  /// Opens the native PDF picker and uploads the choice.
  Future<void> pick(String chatId) async {
    if (of(chatId).length >= maxChatAttachments) {
      return _notice(_failureNotice('too_many'));
    }
    try {
      final api = ref.read(studyBotApiProvider);
      final staged = await ref
          .read(folderAuthorizationProvider)
          .pickPdfForUpload(await api.getIngestStagingDirectory());
      if (staged == null) return;
      await _upload(chatId, staged.stagingId, staged.displayName);
    } on FolderAccessException catch (e) {
      _notice(_failureNotice(e.code));
    } on ApiException {
      _notice(_failureNotice(null));
    }
  }

  /// Uploads PDFs the native layer staged from a drop; rejected files get a short notice.
  Future<void> addDropped(String chatId, List<DroppedPdf> items) async {
    for (final item in items) {
      if (item.error != null || item.stagingId == null) {
        _notice(_failureNotice(item.error));
        continue;
      }
      if (of(chatId).length >= maxChatAttachments) {
        _notice(_failureNotice('too_many'));
        break;
      }
      await _upload(chatId, item.stagingId!, item.displayName);
    }
  }

  Future<void> _upload(
    String chatId,
    String stagingId,
    String displayName,
  ) async {
    final localId = _nextLocalId++;
    _put(chatId, [
      ...of(chatId),
      PendingAttachment(
        localId: localId,
        displayName: displayName,
        status: AttachmentStatus.uploading,
      ),
    ]);
    try {
      final result = await ref
          .read(studyBotApiProvider)
          .uploadPdf(
            stagingId: stagingId,
            displayName: displayName,
            saveToLibrary: false,
          );
      final file = result.file;
      if (result.outcome == 'failed' || file == null) {
        return _update(
          chatId,
          localId,
          (a) => a.copyWith(
            status: AttachmentStatus.failed,
            failure: _failureText(result.failureCode),
          ),
        );
      }
      if (of(chatId).any((a) => a.localId != localId && a.fileId == file.id)) {
        _put(chatId, [
          for (final a in of(chatId))
            if (a.localId != localId) a,
        ]);
        return _notice('That PDF is already attached.');
      }
      _update(
        chatId,
        localId,
        (a) => a.copyWith(
          status: AttachmentStatus.ready,
          fileId: file.id,
          pageCount: file.pageCount,
          textPageCount: file.textPageCount,
        ),
      );
    } on ApiException {
      _update(
        chatId,
        localId,
        (a) => a.copyWith(
          status: AttachmentStatus.failed,
          failure: _failureText(null),
        ),
      );
    }
  }

  void _update(
    String chatId,
    int localId,
    PendingAttachment Function(PendingAttachment) change,
  ) {
    _put(chatId, [
      for (final a in of(chatId)) a.localId == localId ? change(a) : a,
    ]);
  }

  /// Removes a chip before sending. A file that was only uploaded for this message is deleted
  /// on the server; one kept in the library or already attached elsewhere is left alone.
  Future<void> remove(String chatId, int localId) async {
    final target = of(chatId).where((a) => a.localId == localId).firstOrNull;
    if (target == null) return;
    _put(chatId, [
      for (final a in of(chatId))
        if (a.localId != localId) a,
    ]);
    final fileId = target.fileId;
    if (fileId != null) {
      try {
        await ref.read(studyBotApiProvider).discardAttachment(fileId);
      } on ApiException {
        // Unreferenced chat uploads are also cleaned up by the engine later.
      }
    }
  }

  /// Retry for a failed file: the chip is removed and the picker opens again.
  Future<void> retry(String chatId, int localId) async {
    _put(chatId, [
      for (final a in of(chatId))
        if (a.localId != localId) a,
    ]);
    await pick(chatId);
  }

  /// Forgets the chips after the message was sent (the files now belong to the message).
  void clear(String chatId) => _put(chatId, const []);
}

final composerAttachmentsProvider =
    NotifierProvider<ComposerAttachments, Map<String, List<PendingAttachment>>>(
      ComposerAttachments.new,
    );

/// A one-shot message about the last attachment action (shown once as a snack bar).
class AttachmentNotice extends Notifier<String?> {
  @override
  String? build() => null;

  void set(String? message) => state = message;
}

final attachmentNoticeProvider = NotifierProvider<AttachmentNotice, String?>(
  AttachmentNotice.new,
);

/// The window's file-drop service; replaced in tests.
final fileDropServiceProvider = Provider<FileDropService>(
  (ref) => MacOSFileDropService(),
);
