import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_breakpoints.dart';
import '../../core/theme/app_motion.dart';
import '../chats/chats_list_view.dart';
import '../chats/chats_providers.dart';
import '../conversation/conversation_view.dart';
import '../courses/courses_list_view.dart';
import 'nav_rail.dart';
import 'study_panel.dart';

/// The adaptive four-region desktop shell (Navigation | Chats | Conversation
/// | Study panel), collapsing progressively at narrower widths per the
/// design brief's four breakpoints. Continuously resizable — every tier
/// uses `Expanded`/bounded widths so nothing overflows.
class AppShell extends ConsumerWidget {
  const AppShell({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      body: LayoutBuilder(
        builder: (context, constraints) {
          final width = constraints.maxWidth;
          if (AppBreakpoints.isPhoneWidth(width)) {
            return const _PhoneLayout();
          }
          if (width < AppBreakpoints.medium) {
            return const _CompactLayout();
          }
          if (width < AppBreakpoints.large) {
            return const _MediumLayout();
          }
          return const _LargeLayout();
        },
      ),
    );
  }
}

class _LargeLayout extends StatelessWidget {
  const _LargeLayout();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      children: [
        const NavRail(),
        SizedBox(
          width: 240,
          child: DecoratedBox(
            decoration: BoxDecoration(border: Border(right: BorderSide(color: theme.colorScheme.outlineVariant))),
            child: const CoursesListView(),
          ),
        ),
        SizedBox(
          width: 280,
          child: DecoratedBox(
            decoration: BoxDecoration(border: Border(right: BorderSide(color: theme.colorScheme.outlineVariant))),
            child: const ChatsListView(),
          ),
        ),
        const Expanded(child: ConversationView()),
        const SizedBox(width: 300, child: StudyPanel()),
      ],
    );
  }
}

class _MediumLayout extends StatelessWidget {
  const _MediumLayout();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      children: [
        const NavRail(),
        SizedBox(
          width: 220,
          child: DecoratedBox(
            decoration: BoxDecoration(border: Border(right: BorderSide(color: theme.colorScheme.outlineVariant))),
            child: const CoursesListView(),
          ),
        ),
        SizedBox(
          width: 260,
          child: DecoratedBox(
            decoration: BoxDecoration(border: Border(right: BorderSide(color: theme.colorScheme.outlineVariant))),
            child: const ChatsListView(),
          ),
        ),
        const Expanded(child: ConversationView()),
      ],
    );
  }
}

/// Tablet tier: Navigation + Chats collapse into one togglable panel beside
/// the conversation, since there isn't room for three columns.
class _CompactLayout extends StatefulWidget {
  const _CompactLayout();

  @override
  State<_CompactLayout> createState() => _CompactLayoutState();
}

class _CompactLayoutState extends State<_CompactLayout> {
  bool _sidebarOpen = true;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      children: [
        const NavRail(),
        AnimatedContainer(
          duration: AppMotion.normal,
          curve: AppMotion.standardCurve,
          width: _sidebarOpen ? 280 : 0,
          clipBehavior: Clip.hardEdge,
          decoration: BoxDecoration(border: Border(right: BorderSide(color: theme.colorScheme.outlineVariant))),
          // The sidebar's own content (section headers with a trailing
          // IconButton, list tiles, ...) is laid out at a fixed 280px width
          // at all times via OverflowBox — the outer AnimatedContainer just
          // clips it as it shrinks toward 0. A plain SizedBox does not
          // achieve this: it still gets clamped down to whatever (shrinking)
          // constraint AnimatedContainer passes through. Letting the content
          // actually relayout at every intermediate width down to a few
          // pixels produces a real RenderFlex overflow partway through the
          // collapse animation, since a Row with a fixed-size trailing
          // IconButton cannot shrink below that button's own minimum width.
          child: const OverflowBox(
            minWidth: 280,
            maxWidth: 280,
            alignment: Alignment.centerLeft,
            child: _CombinedSidebar(),
          ),
        ),
        Expanded(
          child: Column(
            children: [
              _CompactTopBar(sidebarOpen: _sidebarOpen, onToggle: () => setState(() => _sidebarOpen = !_sidebarOpen)),
              const Expanded(child: ConversationView()),
            ],
          ),
        ),
      ],
    );
  }
}

class _CompactTopBar extends StatelessWidget {
  const _CompactTopBar({required this.sidebarOpen, required this.onToggle});

  final bool sidebarOpen;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Consumer(
      builder: (context, ref, _) {
        final chat = ref.watch(activeChatProvider);
        return Container(
          height: 48,
          padding: const EdgeInsets.symmetric(horizontal: 4),
          decoration: BoxDecoration(border: Border(bottom: BorderSide(color: theme.colorScheme.outlineVariant))),
          child: Row(
            children: [
              IconButton(icon: const Icon(Icons.menu), onPressed: onToggle),
              Expanded(
                child: Text(
                  chat?.displayTitle ?? 'Study Bot',
                  style: theme.textTheme.titleSmall,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _PhoneLayout extends StatelessWidget {
  const _PhoneLayout();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Consumer(
          builder: (context, ref, _) {
            final chat = ref.watch(activeChatProvider);
            return Text(chat?.displayTitle ?? 'Study Bot');
          },
        ),
      ),
      drawer: const Drawer(child: SafeArea(child: _CombinedSidebar())),
      body: const ConversationView(),
    );
  }
}

/// Courses stacked above Chats in a single scrollable column — used by the
/// compact and phone tiers where there isn't room for two side-by-side
/// columns.
class _CombinedSidebar extends StatelessWidget {
  const _CombinedSidebar();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      children: [
        const Expanded(flex: 1, child: CoursesListView()),
        Divider(height: 1, color: theme.colorScheme.outlineVariant),
        const Expanded(flex: 2, child: ChatsListView()),
      ],
    );
  }
}
