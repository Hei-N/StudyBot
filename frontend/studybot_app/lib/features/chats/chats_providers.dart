import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/chat.dart';
import '../connection/connection_providers.dart';
import '../courses/courses_providers.dart';

/// `course_id` query value for "General" (unassigned chats) — see
/// API_CONTRACT.md: omitting the parameter lists *every* chat, which this
/// UI's chat list never wants; it always shows either one course's chats
/// or General's.
const _generalCourseFilter = 'none';

/// Chats for [activeCourseIdProvider] (or General), most recently updated
/// first — exactly the order `GET /chats` already returns.
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

  /// Per API_CONTRACT.md's "Lazy persistence": a brand-new chat has no
  /// database row until its first message completes, so it will not come
  /// back from a `GET /chats` refresh yet — insert the `POST` response
  /// locally instead of refreshing, or it would vanish from the list
  /// immediately after being created.
  Future<Chat> create() async {
    final courseId = ref.read(activeCourseIdProvider);
    final chat = await ref.read(studyBotApiProvider).createChat(courseId: courseId);
    state = AsyncValue.data([chat, ...?state.value]);
    return chat;
  }

  /// Patches the renamed chat in place rather than refreshing — a
  /// never-messaged chat can be renamed (the mutation endpoints work
  /// against it even before it's persisted) but still wouldn't come back
  /// from a list refresh yet; see [create].
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

  /// Patches the mode in place rather than refreshing — see [create] for
  /// why a full refresh isn't safe for a chat that may still be
  /// unpersisted.
  Future<void> setMode(String chatId, String mode) async {
    await ref.read(studyBotApiProvider).setChatMode(chatId, mode);
    final current = state.value;
    if (current == null) return;
    state = AsyncValue.data([
      for (final chat in current)
        if (chat.id == chatId) chat.copyWith(teachingMode: mode) else chat,
    ]);
  }

  void _replaceLocally(Chat chat) {
    final current = state.value;
    if (current == null) return;
    state = AsyncValue.data([for (final c in current) if (c.id == chat.id) chat else c]);
  }
}

final chatsProvider = AsyncNotifierProvider<ChatsNotifier, List<Chat>>(ChatsNotifier.new);

/// The chat currently open in the conversation view. Kept in sync with
/// [chatsProvider] via `ref.listen` (not `ref.watch`, so this notifier's
/// own `build()` never re-runs and its `state` is never implicitly reset):
/// if the current selection disappears (deleted, or the course changed)
/// the most recently updated chat in the new list is selected instead, or
/// `null` if the list is empty.
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

/// The [Chat] object for [activeChatIdProvider], looked up from the
/// already-loaded list (no extra request).
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
