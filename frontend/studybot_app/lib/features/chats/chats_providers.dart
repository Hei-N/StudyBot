import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/chat.dart';
import '../connection/connection_providers.dart';
import '../courses/courses_providers.dart';

/// `course_id` query value for "General" (unassigned chats). Omitting the
/// parameter lists every chat, which the chat list never wants (see
/// API_CONTRACT.md).
const _generalCourseFilter = 'none';

/// Chats for [activeCourseIdProvider] (or General), most recently updated
/// first, as returned by `GET /chats`.
class ChatsNotifier extends AsyncNotifier<List<Chat>> {
  @override
  Future<List<Chat>> build() async {
    final courseId = ref.watch(activeCourseIdProvider);
    return ref.read(studyBotApiProvider).listChats(courseId: courseId ?? _generalCourseFilter);
  }

  Future<void> refresh() async {
    final courseId = ref.read(activeCourseIdProvider);
    state = await AsyncValue.guard(
      () => ref.read(studyBotApiProvider).listChats(courseId: courseId ?? _generalCourseFilter),
    );
  }

  /// Adds the created chat to the list directly instead of refetching.
  Future<Chat> create() async {
    final courseId = ref.read(activeCourseIdProvider);
    final chat = await ref.read(studyBotApiProvider).createChat(courseId: courseId);
    state = AsyncValue.data([chat, ...?state.value]);
    return chat;
  }

  /// Patches the renamed chat in place instead of refetching.
  Future<Chat> rename(String chatId, String title) async {
    final chat = await ref.read(studyBotApiProvider).renameChat(chatId, title);
    _replaceLocally(chat);
    return chat;
  }

  Future<void> delete(String chatId) async {
    await ref.read(studyBotApiProvider).deleteChat(chatId);
    final current = state.value ?? const [];
    state = AsyncValue.data(current.where((c) => c.id != chatId).toList());
  }

  Future<Chat> moveToCourse(String chatId, String? courseId) async {
    final chat = await ref.read(studyBotApiProvider).setChatCourse(chatId, courseId);
    await refresh();
    return chat;
  }

  /// Patches the mode in place instead of refetching.
  Future<void> setMode(String chatId, String mode) async {
    await ref.read(studyBotApiProvider).setChatMode(chatId, mode);
    final current = state.value;
    if (current == null) return;
    state = AsyncValue.data([
      for (final chat in current)
        if (chat.id == chatId) chat.copyWith(teachingMode: mode) else chat,
    ]);
  }

  /// Reasoning mode is independent of teaching mode (see
  /// `core/models/reasoning_mode.dart`); patched the same way.
  Future<void> setReasoningMode(String chatId, String reasoningMode) async {
    await ref.read(studyBotApiProvider).setChatReasoningMode(chatId, reasoningMode);
    final current = state.value;
    if (current == null) return;
    state = AsyncValue.data([
      for (final chat in current)
        if (chat.id == chatId) chat.copyWith(reasoningMode: reasoningMode) else chat,
    ]);
  }

  void _replaceLocally(Chat chat) {
    final current = state.value;
    if (current == null) return;
    state = AsyncValue.data([for (final c in current) if (c.id == chat.id) chat else c]);
  }
}

final chatsProvider = AsyncNotifierProvider<ChatsNotifier, List<Chat>>(ChatsNotifier.new);

/// The chat open in the conversation view. Follows [chatsProvider] via
/// `ref.listen` (not `ref.watch`, so `build()` never re-runs and `state` is not
/// reset): if the selection disappears (deleted, or the course changed), the
/// most recently updated chat in the new list is selected, or `null` if empty.
class ActiveChatIdNotifier extends Notifier<String?> {
  @override
  String? build() {
    ref.listen<AsyncValue<List<Chat>>>(chatsProvider, (previous, next) {
      final chats = next.value;
      if (chats == null) return;
      if (chats.isEmpty) {
        state = null;
        return;
      }
      final current = state;
      if (current == null || chats.every((c) => c.id != current)) {
        state = chats.first.id;
      }
    });
    return null;
  }

  void select(String? chatId) => state = chatId;
}

final activeChatIdProvider = NotifierProvider<ActiveChatIdNotifier, String?>(ActiveChatIdNotifier.new);

/// The [Chat] for [activeChatIdProvider], looked up from the loaded list (no
/// extra request).
final activeChatProvider = Provider<Chat?>((ref) {
  final chatId = ref.watch(activeChatIdProvider);
  if (chatId == null) return null;
  final chats = ref.watch(chatsProvider).value;
  if (chats == null) return null;
  for (final chat in chats) {
    if (chat.id == chatId) return chat;
  }
  return null;
});
