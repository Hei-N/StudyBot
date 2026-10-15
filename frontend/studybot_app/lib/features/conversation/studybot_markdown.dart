import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:markdown/markdown.dart' as md;

/// Renders assistant message text as GitHub-flavored Markdown with LaTeX math.
///
/// Display-only: the source text is never modified. Math is `$..$`, `\(..\)`
/// inline and `$$..$$`, `\[..\]` display. Code spans and fences stay literal,
/// and math that is incomplete (still streaming) or invalid is shown as its
/// source text instead of an error.
class StudyBotMarkdown extends StatelessWidget {
  const StudyBotMarkdown({super.key, required this.data, this.isStreaming = false});

  final String data;

  /// True while the message is still arriving. Incomplete math is already shown
  /// as plain text in every state, so this only documents intent for callers.
  final bool isStreaming;

  static final _extensionSet = md.ExtensionSet(
    [MathBlockSyntax(), ...md.ExtensionSet.gitHubFlavored.blockSyntaxes],
    [MathInlineSyntax(), ...md.ExtensionSet.gitHubFlavored.inlineSyntaxes],
  );

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return MarkdownBody(
      data: data,
      selectable: true,
      extensionSet: _extensionSet,
      builders: {'math': MathElementBuilder(theme.textTheme.bodyMedium)},
      styleSheet: MarkdownStyleSheet.fromTheme(theme).copyWith(
        p: theme.textTheme.bodyMedium,
        code: theme.textTheme.bodyMedium?.copyWith(
          fontFamily: 'monospace',
          backgroundColor: theme.colorScheme.surfaceContainerHighest,
        ),
      ),
    );
  }
}

const _styleAttribute = 'MathStyle';
const _display = 'display';

/// Inline math. A `$` pair only counts when the closing `$` is not followed by
/// a word character and the opening one is not preceded by one, so currency
/// such as `$5 or $10` is left as text.
class MathInlineSyntax extends md.InlineSyntax {
  MathInlineSyntax()
    : super(
        r'\$\$([^\n]+?)\$\$'
        r'|\\\(([^\n]+?)\\\)'
        r'|\\\[([^\n]+?)\\\]'
        r'|(?<![\\$\w])\$(?!\$)([^$\n]+?)\$(?![\w$])',
      );

  @override
  bool onMatch(md.InlineParser parser, Match match) {
    final display = match[1] != null || match[3] != null;
    final source = match[1] ?? match[2] ?? match[3] ?? match[4]!;
    parser.addNode(md.Element.text('math', source)..attributes[_styleAttribute] = display ? _display : 'text');
    return true;
  }
}

/// Display math on its own lines: `$$ ... $$` or `\[ ... \]`, including a
/// single-line `\[ ... \]`. A block is only recognised once its closing
/// delimiter has arrived, so a half-streamed block stays ordinary text.
class MathBlockSyntax extends md.BlockSyntax {
  static final _dollarFence = RegExp(r'^\s*\$\$\s*$');
  static final _bracketOpen = RegExp(r'^\s*\\\[\s*$');
  static final _bracketClose = RegExp(r'^\s*\\\]\s*$');
  static final _bracketSingle = RegExp(r'^\s*\\\[(.+)\\\]\s*$');

  @override
  RegExp get pattern => RegExp(r'^\s*(\$\$|\\\[)');

  @override
  bool canParse(md.BlockParser parser) {
    final line = parser.current.content;
    if (_bracketSingle.hasMatch(line)) return true;
    final closer = _closerFor(line);
    if (closer == null) return false;
    for (var i = 1; parser.peek(i) != null; i++) {
      if (closer.hasMatch(parser.peek(i)!.content)) return true;
    }
    return false;
  }

  RegExp? _closerFor(String line) {
    if (_dollarFence.hasMatch(line)) return _dollarFence;
    if (_bracketOpen.hasMatch(line)) return _bracketClose;
    return null;
  }

  @override
  md.Node parse(md.BlockParser parser) {
    final first = parser.current.content;
    final single = _bracketSingle.firstMatch(first);
    final String source;
    if (single != null) {
      source = single[1]!;
      parser.advance();
    } else {
      final closer = _closerFor(first)!;
      parser.advance();
      final lines = <String>[];
      while (!parser.isDone && !closer.hasMatch(parser.current.content)) {
        lines.add(parser.current.content);
        parser.advance();
      }
      parser.advance();
      source = lines.join('\n');
    }
    return md.Element('p', [md.Element.text('math', source.trim())..attributes[_styleAttribute] = _display]);
  }
}

/// Builds the math widget, falling back to the source text if it can't render.
class MathElementBuilder extends MarkdownElementBuilder {
  MathElementBuilder(this.textStyle);

  final TextStyle? textStyle;

  @override
  Widget? visitElementAfterWithContext(
    BuildContext context,
    md.Element element,
    TextStyle? preferredStyle,
    TextStyle? parentStyle,
  ) {
    final source = element.textContent.trim();
    final isDisplay = element.attributes[_styleAttribute] == _display;
    final style = textStyle ?? parentStyle;
    if (source.isEmpty) return Text(isDisplay ? r'$$' : r'$', style: style);

    final literal = isDisplay ? '\$\$ $source \$\$' : '\$$source\$';
    final math = Semantics(
      label: source,
      child: ExcludeSemantics(
        child: Math.tex(
          source,
          mathStyle: isDisplay ? MathStyle.display : MathStyle.text,
          textStyle: style,
          onErrorFallback: (_) => Text(literal, style: style),
        ),
      ),
    );
    if (!isDisplay) return math;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: SingleChildScrollView(scrollDirection: Axis.horizontal, child: math),
    );
  }
}
