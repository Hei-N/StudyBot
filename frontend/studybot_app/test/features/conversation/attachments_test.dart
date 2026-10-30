import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/chat.dart';
import 'package:studybot_app/core/models/message.dart';
import 'package:studybot_app/core/platform/file_drop.dart';
import 'package:studybot_app/core/platform/folder_authorization.dart';
import 'package:studybot_app/features/chats/chats_providers.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/conversation/attachment_providers.dart';
import 'package:studybot_app/features/conversation/attachment_widgets.dart';
import 'package:studybot_app/features/conversation/composer.dart';
import 'package:studybot_app/features/conversation/message_bubble.dart';
import 'package:studybot_app/features/library/library_providers.dart';

import '../../support/fake_chat_websocket_client.dart';
import '../../support/fake_folder_authorization.dart';
import '../../support/fake_studybot_api.dart';
import '../../support/no_retry_container.dart';

class _FakeDrop implements FileDropService {
  final controller = StreamController<DropEvent>.broadcast();
  final List<bool> accepting = [];

  @override
  Stream<DropEvent> get events => controller.stream;

  @override
  Future<void> setAccepting(bool value, {String? stagingDirectory}) async => accepting.add(value);
}

Chat _chat(String id) =>
    Chat(id: id, title: null, courseId: null, teachingMode: 'teach', reasoningMode: 'fast', createdAt: 'now', updatedAt: 'now');

StagedUpload _staged(String name) => StagedUpload(stagingId: 'stage-$name', displayName: name, sizeBytes: 100);

class _Harness {
  _Harness(this.api, this.ws, this.folders, this.drop, this.container);
  final FakeStudyBotApi api;
  final FakeChatWebSocketClient ws;
  final FakeFolderAuthorization folders;
  final _FakeDrop drop;
  final ProviderContainer container;
}

Future<_Harness> _pump(WidgetTester tester, {double width = 900}) async {
  final api = FakeStudyBotApi(chats: [_chat('chat1'), _chat('chat2')]);
  final ws = FakeChatWebSocketClient();
  final folders = FakeFolderAuthorization();
  final drop = _FakeDrop();
  addTearDown(drop.controller.close);
  final container = ProviderContainer(
    overrides: [
      studyBotApiProvider.overrideWithValue(api),
      chatWebSocketClientProvider.overrideWithValue(ws),
      folderAuthorizationProvider.overrideWithValue(folders),
      fileDropServiceProvider.overrideWithValue(drop),
    ],
    retry: kNoRetry,
  );
  addTearDown(container.dispose);
  container.read(activeChatIdProvider.notifier).select('chat1');
  await container.read(chatsProvider.future);
  tester.view.physicalSize = Size(width, 700);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(
        home: Scaffold(
          body: AttachmentDropZone(
            chatId: 'chat1',
            child: const Align(alignment: Alignment.bottomCenter, child: Composer()),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
  return _Harness(api, ws, folders, drop, container);
}

Future<void> _attachViaMenu(WidgetTester tester) async {
  await tester.tap(find.byIcon(Icons.add));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Upload PDF'));
  await tester.pumpAndSettle();
}

final _send = find.widgetWithIcon(IconButton, Icons.arrow_upward);

void main() {
  testWidgets('the + menu offers Upload PDF and attaches a chip that becomes Ready', (tester) async {
    final h = await _pump(tester);
    h.folders.uploadPicks.add(_staged('notes.pdf'));

    await tester.tap(find.byIcon(Icons.add));
    await tester.pumpAndSettle();
    expect(find.text('Upload PDF'), findsOneWidget);
    await tester.tap(find.text('Upload PDF'));
    await tester.pumpAndSettle();

    expect(find.text('notes.pdf'), findsOneWidget);
    expect(find.text('Ready'), findsOneWidget);
    expect(h.api.uploadSaveFlags, [false], reason: 'chat uploads must not enter the Study Library');
    expect(find.textContaining("can't use them in answers yet"), findsOneWidget);
  });

  testWidgets('cancelling the picker adds nothing', (tester) async {
    final h = await _pump(tester);
    await _attachViaMenu(tester);
    expect(find.byType(AttachmentChip), findsNothing);
    expect(h.api.uploadSaveFlags, isEmpty);
  });

  testWidgets('a failed upload shows Failed and Retry succeeds', (tester) async {
    final h = await _pump(tester);
    h.folders.uploadPicks.add(_staged('bad.pdf'));
    h.api.nextUploadOutcome = 'failed';
    await _attachViaMenu(tester);

    expect(find.text('Retry'), findsOneWidget);
    expect(_sendEnabled(tester), isFalse);

    h.api.nextUploadOutcome = 'uploaded';
    h.folders.uploadPicks.add(_staged('bad.pdf'));
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();
    expect(find.text('Ready'), findsOneWidget);
    expect(find.text('Retry'), findsNothing);
  });

  testWidgets('removing a chip before sending discards the upload', (tester) async {
    final h = await _pump(tester);
    h.folders.uploadPicks.add(_staged('a.pdf'));
    await _attachViaMenu(tester);

    await tester.tap(find.byTooltip('Remove a.pdf'));
    await tester.pumpAndSettle();

    expect(find.byType(AttachmentChip), findsNothing);
    expect(h.api.discardedAttachments, ['chat-file-1']);
  });

  testWidgets('several PDFs show several chips and are capped at five', (tester) async {
    final h = await _pump(tester);
    for (var i = 1; i <= 6; i++) {
      h.folders.uploadPicks.add(_staged('f$i.pdf'));
    }
    for (var i = 0; i < 6; i++) {
      await _attachViaMenu(tester);
    }
    expect(h.container.read(composerAttachmentsProvider.notifier).of('chat1'), hasLength(5));
    expect(h.api.chatUploads, hasLength(5));
  });

  testWidgets('attaching the same PDF twice keeps one chip', (tester) async {
    final h = await _pump(tester);
    h.folders.uploadPicks.addAll([_staged('same.pdf'), _staged('same.pdf')]);
    await _attachViaMenu(tester);
    await _attachViaMenu(tester);
    expect(h.container.read(composerAttachmentsProvider.notifier).of('chat1'), hasLength(1));
  });

  testWidgets('sending carries the attachment ids and clears the chips', (tester) async {
    final h = await _pump(tester);
    h.folders.uploadPicks.add(_staged('hw.pdf'));
    await _attachViaMenu(tester);

    await tester.enterText(find.byType(TextField), 'Help me with this PDF.');
    await tester.pump();
    await tester.tap(_send);
    await tester.pumpAndSettle();

    expect(h.ws.sentMessages.single.content, 'Help me with this PDF.');
    expect(h.ws.sentMessages.single.attachmentIds, ['chat-file-1']);
    expect(find.byType(AttachmentChip), findsNothing);
    expect(h.api.discardedAttachments, isEmpty, reason: 'a sent attachment must not be discarded');
  });

  testWidgets('plain text sending is unchanged', (tester) async {
    final h = await _pump(tester);
    await tester.enterText(find.byType(TextField), 'hello');
    await tester.pump();
    await tester.tap(_send);
    await tester.pumpAndSettle();
    expect(h.ws.sentMessages.single.attachmentIds, isEmpty);
  });

  testWidgets('attachments belong to their own chat', (tester) async {
    final h = await _pump(tester);
    h.folders.uploadPicks.add(_staged('only1.pdf'));
    await _attachViaMenu(tester);

    h.container.read(activeChatIdProvider.notifier).select('chat2');
    await tester.pumpAndSettle();
    expect(find.text('only1.pdf'), findsNothing);

    h.container.read(activeChatIdProvider.notifier).select('chat1');
    await tester.pumpAndSettle();
    expect(find.text('only1.pdf'), findsOneWidget);
  });

  testWidgets('dragging a PDF shows the drop cue, dropping attaches it', (tester) async {
    final h = await _pump(tester);
    expect(h.drop.accepting, contains(true));

    h.drop.controller.add(const DragEntered(valid: true, count: 1));
    await tester.pumpAndSettle();
    expect(find.text('Drop PDF to attach'), findsOneWidget);

    h.drop.controller.add(const DragExited());
    await tester.pumpAndSettle();
    expect(find.text('Drop PDF to attach'), findsNothing);

    h.drop.controller.add(const Dropped([DroppedPdf(displayName: 'dropped.pdf', sizeBytes: 10, stagingId: 's1')]));
    await tester.pumpAndSettle();
    expect(find.text('dropped.pdf'), findsOneWidget);
    expect(h.api.uploadSaveFlags, [false]);
  });

  testWidgets('dragging a non-PDF is rejected cleanly', (tester) async {
    final h = await _pump(tester);
    h.drop.controller.add(const DragEntered(valid: false, count: 1));
    await tester.pumpAndSettle();
    expect(find.text('Only PDF files can be attached'), findsOneWidget);

    h.drop.controller.add(const Dropped([DroppedPdf(displayName: 'pic.png', sizeBytes: 10, error: 'not_pdf')]));
    await tester.pumpAndSettle();
    expect(h.api.uploadSaveFlags, isEmpty);
    expect(h.container.read(composerAttachmentsProvider.notifier).of('chat1'), isEmpty);
    expect(find.text('Please choose a PDF file.'), findsOneWidget);
  });

  testWidgets('the composer fits a narrow window with chips present', (tester) async {
    final h = await _pump(tester, width: 700);
    h.folders.uploadPicks.add(_staged('a-rather-long-document-name-for-layout-testing.pdf'));
    await _attachViaMenu(tester);
    expect(tester.takeException(), isNull);
    expect(find.byType(AttachmentChip), findsOneWidget);
  });

  testWidgets('a sent message shows its attachments, and history parses them', (tester) async {
    final message = ChatMessage.fromJson({
      'id': 1,
      'createdAt': 'now',
      'role': 'user',
      'content': 'Help me with this PDF.',
      'attachments': [
        {'id': 1, 'fileId': 'f1', 'displayName': 'hw.pdf', 'pageCount': 3, 'textPageCount': 3, 'processingState': 'ready'},
      ],
    });
    expect(message.attachments.single.displayName, 'hw.pdf');

    await tester.pumpWidget(MaterialApp(home: Scaffold(body: MessageBubble(message: message))));
    expect(find.text('hw.pdf'), findsOneWidget);
    expect(find.text('3 pages'), findsOneWidget);
    expect(find.text('Help me with this PDF.'), findsOneWidget);
  });

  testWidgets('a message without attachments has none', (tester) async {
    final message = ChatMessage.fromJson({'id': 2, 'role': 'user', 'content': 'hi', 'createdAt': 'now'});
    expect(message.attachments, isEmpty);
  });
}

bool _sendEnabled(WidgetTester tester) => tester.widget<IconButton>(_send).onPressed != null;
