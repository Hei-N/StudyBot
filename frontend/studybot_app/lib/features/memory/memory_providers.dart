import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/learning_memory.dart';
import '../connection/connection_providers.dart';
import '../courses/courses_providers.dart';

/// The kind catalog (`GET /memory-kinds`) — always five entries with
/// natural-language display metadata, never hardcoded here.
final memoryKindCatalogProvider = FutureProvider<List<MemoryKindInfo>>((ref) {
  return ref.read(studyBotApiProvider).listMemoryKinds();
});

/// Every learning memory, unfiltered. The Study Panel and the management
/// view both derive their own filtered views from this single fetch
/// (client-side filtering) rather than each maintaining separate
/// server-filtered queries — memory counts are small enough in Stage 6
/// that this stays simple and keeps every view consistent after a single
/// mutation triggers one `refresh()`.
class MemoriesNotifier extends AsyncNotifier<List<LearningMemory>> {
  @override
  Future<List<LearningMemory>> build() => _fetch();

  Future<List<LearningMemory>> _fetch() => ref.read(studyBotApiProvider).listMemories();

  Future<void> refresh() async {
    state = await AsyncValue.guard(_fetch);
  }

  Future<LearningMemory> create({
    required String topic,
    required String kind,
    required String summary,
    String? courseId,
    String? sourceChatId,
  }) async {
    final memory = await ref
        .read(studyBotApiProvider)
        .createMemory(topic: topic, kind: kind, summary: summary, courseId: courseId, sourceChatId: sourceChatId);
    await refresh();
    return memory;
  }

  Future<LearningMemory> edit(
    String memoryId, {
    required String topic,
    required String kind,
    required String summary,
    bool setCourseId = false,
    String? courseId,
  }) async {
    final memory = await ref
        .read(studyBotApiProvider)
        .updateMemory(memoryId, topic: topic, kind: kind, summary: summary, setCourseId: setCourseId, courseId: courseId);
    await refresh();
    return memory;
  }

  Future<void> archive(String memoryId) async {
    await ref.read(studyBotApiProvider).archiveMemory(memoryId);
    await refresh();
  }

  Future<void> restore(String memoryId) async {
    await ref.read(studyBotApiProvider).restoreMemory(memoryId);
    await refresh();
  }

  Future<void> delete(String memoryId) async {
    await ref.read(studyBotApiProvider).deleteMemory(memoryId);
    await refresh();
  }
}

final memoriesProvider = AsyncNotifierProvider<MemoriesNotifier, List<LearningMemory>>(MemoriesNotifier.new);

/// Active memories relevant to the currently active course (course-specific
/// plus global), for the Study Panel's compact summary — mirrors the
/// backend's own "course-specific first, then global" preference, though
/// here it's just a filter (the backend already applies the real
/// deterministic limit when composing model context; this is a small,
/// already-fetched list for display, not sent to any model).
final activeCourseMemoriesProvider = Provider<List<LearningMemory>>((ref) {
  final all = ref.watch(memoriesProvider).value ?? const [];
  final activeCourseId = ref.watch(activeCourseIdProvider);
  return all.where((m) => m.isActive && (m.courseId == activeCourseId || m.courseId == null)).toList();
});
