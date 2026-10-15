import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/learning_memory.dart';
import '../connection/connection_providers.dart';
import '../courses/courses_providers.dart';

/// The kind catalog (`GET /memory-kinds`): five entries with display metadata
/// from the backend.
final memoryKindCatalogProvider = FutureProvider<List<MemoryKindInfo>>((ref) {
  return ref.read(studyBotApiProvider).listMemoryKinds();
});

/// Every learning memory, unfiltered. The Study Panel and the management view
/// filter this single fetch client-side, which keeps them consistent after one
/// `refresh()`; memory counts are small enough for that.
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

/// Active memories relevant to the active course (course-specific plus global),
/// for the Study Panel summary. A display filter only; the backend applies its
/// own limits when composing model context.
final activeCourseMemoriesProvider = Provider<List<LearningMemory>>((ref) {
  final all = ref.watch(memoriesProvider).value ?? const [];
  final activeCourseId = ref.watch(activeCourseIdProvider);
  return all.where((m) => m.isActive && (m.courseId == activeCourseId || m.courseId == null)).toList();
});
