import 'package:studybot_app/core/api/api_exception.dart';
import 'package:studybot_app/core/api/connection_config.dart';
import 'package:studybot_app/core/api/studybot_api.dart';
import 'package:studybot_app/core/models/chat.dart';
import 'package:studybot_app/core/models/course.dart';
import 'package:studybot_app/core/models/health.dart';
import 'package:studybot_app/core/models/learning_memory.dart';
import 'package:studybot_app/core/models/library_source.dart';
import 'package:studybot_app/core/models/message.dart';
import 'package:studybot_app/core/models/reasoning_mode.dart';
import 'package:studybot_app/core/models/teaching_mode.dart';

const _testConfig = ConnectionConfig(baseUrl: 'http://fake', token: 'fake-token');

/// An in-memory stand-in for [StudyBotApi] for provider tests, so notifier
/// logic runs without HTTP. Seed the lists in the constructor; calls are
/// recorded in `calls` for assertions like "listChats was called with
/// courseId=none".
class FakeStudyBotApi extends StudyBotApi {
  FakeStudyBotApi({
    List<Course>? courses,
    List<Chat>? chats,
    List<TeachingModeInfo>? modes,
    List<ReasoningModeInfo>? reasoningModes,
    List<MemoryKindInfo>? memoryKinds,
    List<LearningMemory>? memories,
  }) : courses = courses ?? [],
       chats = chats ?? [],
       modes = modes ?? const [],
       reasoningModes = reasoningModes ?? const [],
       memoryKinds = memoryKinds ?? _defaultMemoryKinds,
       memories = memories ?? [],
       super(_testConfig);

  static const _defaultMemoryKinds = [
    MemoryKindInfo(id: 'understands', displayName: 'Understands', description: 'Understood.'),
    MemoryKindInfo(id: 'needs_review', displayName: 'Needs review', description: 'Should revisit.'),
    MemoryKindInfo(id: 'misconception', displayName: 'Misconception', description: 'Mistaken belief.'),
    MemoryKindInfo(id: 'learning_goal', displayName: 'Goal', description: 'Wants to work toward.'),
    MemoryKindInfo(id: 'useful_strategy', displayName: 'Helpful approach', description: 'Worked well before.'),
  ];

  final List<Course> courses;
  final List<Chat> chats;
  final List<TeachingModeInfo> modes;
  final List<ReasoningModeInfo> reasoningModes;
  final List<MemoryKindInfo> memoryKinds;
  final List<LearningMemory> memories;
  final List<String> calls = [];
  ApiException? nextError;

  /// Chat ids that the list endpoint does not return yet: excluded from
  /// [listChats] and 404 from [getChatMessages]/[getChat] until [persist] is
  /// called.
  final Set<String> phantomChatIds = {};

  void persist(String chatId) => phantomChatIds.remove(chatId);

  ApiException get _chatNotFound => const ApiException(code: ApiErrorCode.chatNotFound, message: 'No such chat.');
  ApiException get _memoryNotFound =>
      const ApiException(code: ApiErrorCode.memoryNotFound, message: 'No such memory.');

  int _idSeed = 100;

  void _maybeThrow() {
    final error = nextError;
    if (error != null) {
      nextError = null;
      throw error;
    }
  }

  @override
  Future<EngineHealth> getHealth() async {
    calls.add('getHealth');
    _maybeThrow();
    return const EngineHealth(
      apiVersion: '1',
      status: 'ok',
      provider: 'ollama',
      model: 'qwen3:4b',
      providerReachable: true,
      modelAvailable: true,
    );
  }

  @override
  Future<List<Course>> listCourses() async {
    calls.add('listCourses');
    _maybeThrow();
    return List.of(courses);
  }

  @override
  Future<Course> createCourse({required String name, String? code, String? term, String? description}) async {
    calls.add('createCourse:$name');
    _maybeThrow();
    final course = Course(
      id: 'course-${_idSeed++}',
      name: name,
      code: code,
      term: term,
      description: description,
      createdAt: 'now',
      updatedAt: 'now',
    );
    courses.add(course);
    return course;
  }

  @override
  Future<Course> updateCourse(
    String courseId, {
    required String name,
    String? code,
    String? term,
    String? description,
  }) async {
    calls.add('updateCourse:$courseId');
    _maybeThrow();
    final index = courses.indexWhere((c) => c.id == courseId);
    final updated = Course(
      id: courseId,
      name: name,
      code: code,
      term: term,
      description: description,
      createdAt: 'now',
      updatedAt: 'now',
    );
    courses[index] = updated;
    return updated;
  }

  @override
  Future<void> deleteCourse(String courseId) async {
    calls.add('deleteCourse:$courseId');
    _maybeThrow();
    courses.removeWhere((c) => c.id == courseId);
    for (var i = 0; i < chats.length; i++) {
      if (chats[i].courseId == courseId) {
        chats[i] = chats[i].copyWith(clearCourseId: true);
      }
    }
  }

  @override
  Future<List<TeachingModeInfo>> listModes() async {
    calls.add('listModes');
    _maybeThrow();
    return List.of(modes);
  }

  @override
  Future<List<ReasoningModeInfo>> listReasoningModes() async {
    calls.add('listReasoningModes');
    _maybeThrow();
    return List.of(reasoningModes);
  }

  @override
  Future<List<Chat>> listChats({String? courseId}) async {
    calls.add('listChats:${courseId ?? '<all>'}');
    _maybeThrow();
    final visible = chats.where((c) => !phantomChatIds.contains(c.id));
    if (courseId == null) return visible.toList();
    if (courseId == 'none') return visible.where((c) => c.courseId == null).toList();
    return visible.where((c) => c.courseId == courseId).toList();
  }

  @override
  Future<Chat> createChat({String? courseId}) async {
    calls.add('createChat:$courseId');
    _maybeThrow();
    final chat = Chat(
      id: 'chat-${_idSeed++}',
      title: null,
      courseId: courseId,
      teachingMode: modes.isNotEmpty ? modes.first.id : 'teach',
      reasoningMode: 'fast',
      createdAt: 'now',
      updatedAt: 'now',
    );
    chats.insert(0, chat);
    return chat;
  }

  @override
  Future<Chat> getChat(String chatId) async {
    calls.add('getChat:$chatId');
    _maybeThrow();
    if (phantomChatIds.contains(chatId)) throw _chatNotFound;
    return chats.firstWhere((c) => c.id == chatId, orElse: () => throw _chatNotFound);
  }

  final Map<String, List<ChatMessage>> messagesByChat = {};

  @override
  Future<List<ChatMessage>> getChatMessages(String chatId) async {
    calls.add('getChatMessages:$chatId');
    _maybeThrow();
    if (phantomChatIds.contains(chatId)) throw _chatNotFound;
    return List.of(messagesByChat[chatId] ?? const []);
  }

  @override
  Future<Chat> renameChat(String chatId, String title) async {
    calls.add('renameChat:$chatId:$title');
    _maybeThrow();
    final index = chats.indexWhere((c) => c.id == chatId);
    final updated = chats[index].copyWith(title: title);
    chats[index] = updated;
    return updated;
  }

  @override
  Future<void> deleteChat(String chatId) async {
    calls.add('deleteChat:$chatId');
    _maybeThrow();
    chats.removeWhere((c) => c.id == chatId);
  }

  @override
  Future<Chat> setChatCourse(String chatId, String? courseId) async {
    calls.add('setChatCourse:$chatId:$courseId');
    _maybeThrow();
    final index = chats.indexWhere((c) => c.id == chatId);
    final updated = chats[index].copyWith(courseId: courseId, clearCourseId: courseId == null);
    chats[index] = updated;
    return updated;
  }

  @override
  Future<TeachingModeInfo> setChatMode(String chatId, String mode) async {
    calls.add('setChatMode:$chatId:$mode');
    _maybeThrow();
    final index = chats.indexWhere((c) => c.id == chatId);
    chats[index] = chats[index].copyWith(teachingMode: mode);
    return modes.where((m) => m.id == mode).firstOrNull ??
        TeachingModeInfo(id: mode, displayName: mode, description: '');
  }

  @override
  Future<ReasoningModeInfo> getChatReasoningMode(String chatId) async {
    calls.add('getChatReasoningMode:$chatId');
    _maybeThrow();
    final chat = chats.firstWhere((c) => c.id == chatId, orElse: () => throw _chatNotFound);
    return reasoningModes.where((m) => m.id == chat.reasoningMode).firstOrNull ??
        ReasoningModeInfo(id: chat.reasoningMode, displayName: chat.reasoningMode, description: '');
  }

  @override
  Future<ReasoningModeInfo> setChatReasoningMode(String chatId, String reasoningMode) async {
    calls.add('setChatReasoningMode:$chatId:$reasoningMode');
    _maybeThrow();
    final index = chats.indexWhere((c) => c.id == chatId);
    chats[index] = chats[index].copyWith(reasoningMode: reasoningMode);
    return reasoningModes.where((m) => m.id == reasoningMode).firstOrNull ??
        ReasoningModeInfo(id: reasoningMode, displayName: reasoningMode, description: '');
  }

  // --- learning memory --------------------------------------------------------

  int _memoryIdSeed = 100;

  @override
  Future<List<MemoryKindInfo>> listMemoryKinds() async {
    calls.add('listMemoryKinds');
    _maybeThrow();
    return List.of(memoryKinds);
  }

  @override
  Future<List<LearningMemory>> listMemories({String? courseId, String? kind, String? status}) async {
    calls.add('listMemories:${courseId ?? '<all>'}:${kind ?? '<all>'}:${status ?? '<all>'}');
    _maybeThrow();
    return memories.where((m) {
      if (courseId == 'none' && m.courseId != null) return false;
      if (courseId != null && courseId != 'none' && m.courseId != courseId) return false;
      if (kind != null && m.kind != kind) return false;
      if (status != null && m.status != status) return false;
      return true;
    }).toList();
  }

  @override
  Future<LearningMemory> createMemory({
    required String topic,
    required String kind,
    required String summary,
    String? courseId,
    String? sourceChatId,
  }) async {
    calls.add('createMemory:$topic:$kind');
    _maybeThrow();
    final memory = LearningMemory(
      id: 'memory-${_memoryIdSeed++}',
      courseId: courseId,
      sourceChatId: sourceChatId,
      topic: topic,
      kind: kind,
      summary: summary,
      status: 'active',
      createdAt: 'now',
      updatedAt: 'now',
    );
    memories.insert(0, memory);
    return memory;
  }

  @override
  Future<LearningMemory> getMemory(String memoryId) async {
    calls.add('getMemory:$memoryId');
    _maybeThrow();
    return memories.firstWhere((m) => m.id == memoryId, orElse: () => throw _memoryNotFound);
  }

  @override
  Future<LearningMemory> updateMemory(
    String memoryId, {
    String? topic,
    String? kind,
    String? summary,
    bool setCourseId = false,
    String? courseId,
  }) async {
    calls.add('updateMemory:$memoryId');
    _maybeThrow();
    final index = memories.indexWhere((m) => m.id == memoryId);
    if (index == -1) throw _memoryNotFound;
    final current = memories[index];
    final updated = LearningMemory(
      id: current.id,
      courseId: setCourseId ? courseId : current.courseId,
      sourceChatId: current.sourceChatId,
      topic: topic ?? current.topic,
      kind: kind ?? current.kind,
      summary: summary ?? current.summary,
      status: current.status,
      createdAt: current.createdAt,
      updatedAt: 'now',
    );
    memories[index] = updated;
    return updated;
  }

  @override
  Future<LearningMemory> archiveMemory(String memoryId) => _setMemoryStatus(memoryId, 'archived');

  @override
  Future<LearningMemory> restoreMemory(String memoryId) => _setMemoryStatus(memoryId, 'active');

  Future<LearningMemory> _setMemoryStatus(String memoryId, String status) async {
    calls.add('setMemoryStatus:$memoryId:$status');
    _maybeThrow();
    final index = memories.indexWhere((m) => m.id == memoryId);
    if (index == -1) throw _memoryNotFound;
    final current = memories[index];
    final updated = LearningMemory(
      id: current.id,
      courseId: current.courseId,
      sourceChatId: current.sourceChatId,
      topic: current.topic,
      kind: current.kind,
      summary: current.summary,
      status: status,
      createdAt: current.createdAt,
      updatedAt: 'now',
    );
    memories[index] = updated;
    return updated;
  }

  @override
  Future<void> deleteMemory(String memoryId) async {
    calls.add('deleteMemory:$memoryId');
    _maybeThrow();
    final existed = memories.any((m) => m.id == memoryId);
    if (!existed) throw _memoryNotFound;
    memories.removeWhere((m) => m.id == memoryId);
  }

  // --- study library -----------------------------------------------------------

  final List<LibrarySource> librarySources = [];

  /// Source id to stored authorization payload (Base64).
  final Map<String, String> libraryAuthorizations = {};
  int _nextSourceId = 1;

  static String _normalizeLocator(String path) => path.replaceAll(RegExp(r'/+$'), '');

  @override
  Future<List<LibrarySource>> listLibrarySources() async {
    calls.add('listLibrarySources');
    _maybeThrow();
    return [
      for (final s in librarySources)
        LibrarySource(
          id: s.id,
          courseId: s.courseId,
          kind: s.kind,
          displayName: s.displayName,
          locator: s.locator,
          hasAuthorization: libraryAuthorizations.containsKey(s.id),
        ),
    ];
  }

  @override
  Future<LibrarySource> authorizeLocalFolder({
    required String displayName,
    required String locator,
    required String bookmark,
  }) async {
    calls.add('authorizeLocalFolder');
    _maybeThrow();
    final normalized = _normalizeLocator(locator);
    var source = librarySources.where((s) => s.locator == normalized).firstOrNull;
    source ??= LibrarySource(
      id: 'source-${_nextSourceId++}',
      courseId: null,
      kind: 'local_folder',
      displayName: displayName,
      locator: normalized,
      hasAuthorization: true,
    );
    if (!librarySources.contains(source)) librarySources.add(source);
    libraryAuthorizations[source.id] = bookmark;
    return source;
  }

  @override
  Future<LibraryAuthorization> getLibraryAuthorization(String sourceId) async {
    calls.add('getLibraryAuthorization:$sourceId');
    _maybeThrow();
    final payload = libraryAuthorizations[sourceId];
    if (payload == null) {
      throw const ApiException(code: 'LIBRARY_AUTHORIZATION_NOT_FOUND', message: 'No authorization.', statusCode: 404);
    }
    return LibraryAuthorization(sourceId: sourceId, platform: 'macos', kind: 'security_scoped_bookmark', payload: payload);
  }

  @override
  Future<LibrarySource> replaceLibraryAuthorization(String sourceId, {required String bookmark}) async {
    calls.add('replaceLibraryAuthorization:$sourceId');
    _maybeThrow();
    final source = librarySources.firstWhere((s) => s.id == sourceId);
    libraryAuthorizations[sourceId] = bookmark;
    return source;
  }

  @override
  Future<void> deleteLibrarySource(String sourceId) async {
    calls.add('deleteLibrarySource:$sourceId');
    _maybeThrow();
    librarySources.removeWhere((s) => s.id == sourceId);
    libraryAuthorizations.remove(sourceId);
  }
}
