import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/message.dart';
import 'package:studybot_app/features/conversation/message_bubble.dart';
import 'package:studybot_app/features/conversation/studybot_markdown.dart';

Future<void> _pump(WidgetTester tester, String data, {double width = 640, bool streaming = false}) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: Align(
          alignment: Alignment.topLeft,
          child: SizedBox(
            width: width,
            child: SingleChildScrollView(
              child: StudyBotMarkdown(data: data, isStreaming: streaming),
            ),
          ),
        ),
      ),
    ),
  );
}

/// Selectable Markdown text plus the glyphs of any rendered math.
String _visible(WidgetTester tester) {
  final selectable = tester
      .widgetList<SelectableText>(find.byType(SelectableText))
      .map((t) => t.textSpan?.toPlainText() ?? t.data ?? '');
  final math = tester.widgetList<RichText>(find.descendant(of: find.byType(Math), matching: find.byType(RichText)));
  return [...selectable, ...math.map((r) => r.text.toPlainText())].join(' ').replaceAll('\uFFFC', '');
}

int _mathCount() => find.byType(Math).evaluate().length;

bool _showsDelimiters(WidgetTester tester) {
  final text = _visible(tester);
  return text.contains(r'$') || text.contains(r'\(') || text.contains(r'\[') || text.contains(r'\frac');
}

void main() {
  group('Markdown', () {
    testWidgets('renders the GFM syntax set', (tester) async {
      await _pump(
        tester,
        '# Title\n\nPlain with **bold** and *italic* and `code` and [OpenAI](https://openai.com).\n\n'
        '- one\n- two\n\n1. first\n2. second\n\n> quoted\n\n```python\nx = 1\n```\n\n'
        '| Variable | Meaning |\n|---|---|\n| v | velocity |\n| a | acceleration |',
      );

      final text = _visible(tester);
      for (final expected in [
        'Title',
        'bold',
        'italic',
        'code',
        'OpenAI',
        'one',
        'two',
        'first',
        'second',
        'quoted',
        'x = 1',
        'Variable',
        'velocity',
        'acceleration',
      ]) {
        expect(text, contains(expected));
      }
      expect(find.byType(Table), findsOneWidget);
      expect(_mathCount(), 0);
      expect(tester.takeException(), isNull);
    });

    testWidgets('links keep their tap handling', (tester) async {
      await _pump(tester, '[OpenAI](https://openai.com)');

      final spans = <TextSpan>[];
      void visit(InlineSpan span) {
        if (span is TextSpan) {
          if (span.recognizer is TapGestureRecognizer) spans.add(span);
          span.children?.forEach(visit);
        }
      }

      for (final text in tester.widgetList<SelectableText>(find.byType(SelectableText))) {
        final span = text.textSpan;
        if (span != null) visit(span);
      }
      expect(spans, isNotEmpty);
    });
  });

  group('Inline and display math', () {
    for (final entry in {
      r'dollar': r'The formula is $E = mc^2$.',
      r'paren': r'The formula is \(E = mc^2\).',
      r'spaced': r'The formula is $ E = mc^2 $.',
      r'inside parens': r'Velocity ($v$) and force \(F\); done',
    }.entries) {
      testWidgets('inline ${entry.key}', (tester) async {
        await _pump(tester, entry.value);

        expect(_mathCount(), greaterThan(0));
        expect(_visible(tester), anyOf(contains('The formula is'), contains('Velocity')));
        expect(_showsDelimiters(tester), isFalse);
        expect(tester.takeException(), isNull);
      });
    }

    for (final entry in {
      'dollars': '\$\$\n\\frac{dy}{dx}=10(2x+3)^4\n\$\$',
      'brackets': '\\[\n\\frac{dy}{dx}=10(2x+3)^4\n\\]',
      'single-line brackets': '\\[ \\frac{dy}{dx}=10(2x+3)^4 \\]',
      'compact': '\$\$x^2+y^2=z^2\$\$',
    }.entries) {
      testWidgets('display ${entry.key}', (tester) async {
        await _pump(tester, 'The derivative is\n\n${entry.value}\n\nDone.');

        expect(_mathCount(), 1);
        expect(_visible(tester), contains('The derivative is'));
        expect(_visible(tester), contains('Done.'));
        expect(_showsDelimiters(tester), isFalse);
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets('renders every required construct without errors', (tester) async {
      const expressions = [
        r'\frac{a}{b}',
        r'x^2',
        r'v_0',
        r'\sqrt{x}',
        r'\alpha \beta \theta \rho \Delta',
        r'\frac{dy}{dx}',
        r'\int_0^1 x^2 dx',
        r'\sum_{i=1}^{n} i',
        r'v_f = v_i + at',
        r'\vec{v}',
        '\\begin{bmatrix}\n1 & 2 \\\\\n3 & 4\n\\end{bmatrix}',
        r'\left( \frac{a}{b} \right)',
        r'5\,\text{kg}',
      ];
      for (final expression in expressions) {
        await _pump(tester, '\$\$\n$expression\n\$\$');
        expect(_mathCount(), 1, reason: expression);
        expect(_showsDelimiters(tester), isFalse, reason: expression);
        expect(tester.takeException(), isNull, reason: expression);
      }
    });

    testWidgets('math works inside lists and table cells', (tester) async {
      await _pump(tester, '- one \$a^2\$\n- two\n\n| Formula | Meaning |\n|---|---|\n| \$F=ma\$ | Newton |');

      expect(_mathCount(), 2);
      expect(_visible(tester), contains('Newton'));
      expect(tester.takeException(), isNull);
    });
  });

  group('Currency stays text', () {
    for (final text in [
      r'The book costs $5.',
      r'The total is $19.99.',
      r'It costs $5 or $10 depending on size.',
      r'I saved $100 today.',
      r'Between $5 and $10, pick one.',
      r'Total: $5 + $3 = $8',
    ]) {
      testWidgets(text, (tester) async {
        await _pump(tester, text);

        expect(_mathCount(), 0);
        expect(_visible(tester), contains(text));
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets(r'escaped \$5 renders as a literal dollar amount', (tester) async {
      await _pump(tester, r'It costs \$5 and \$10.');

      expect(_mathCount(), 0);
      expect(_visible(tester), contains(r'It costs $5 and $10.'));
    });

    testWidgets('a real equation next to currency still renders', (tester) async {
      await _pump(tester, r'It costs $5, and the speed is $v = d/t$ here.');

      expect(_mathCount(), 1);
      expect(_visible(tester), contains(r'$5'));
    });
  });

  group('Code wins over math', () {
    testWidgets('inline code keeps dollars and TeX literal', (tester) async {
      await _pump(tester, r'Use `$HOME` and `\frac{a}{b}` and `$x$` here.');

      expect(_mathCount(), 0);
      expect(_visible(tester), contains(r'$HOME'));
      expect(_visible(tester), contains(r'\frac{a}{b}'));
      expect(_visible(tester), contains(r'$x$'));
    });

    testWidgets('fenced code keeps dollars and TeX literal', (tester) async {
      await _pump(tester, '```text\n\$HOME\n\\frac{a}{b}\n\$\$\n\\[\n```');

      expect(_mathCount(), 0);
      expect(_visible(tester), contains(r'$HOME'));
      expect(_visible(tester), contains(r'\frac{a}{b}'));
      expect(tester.takeException(), isNull);
    });

    testWidgets('code and math side by side', (tester) async {
      await _pump(tester, 'Code:\n\n```python\nprice = "\$5"\n```\n\nFormula \$E = mc^2\$.');

      expect(_mathCount(), 1);
      expect(_visible(tester), contains('price = "\$5"'));
    });
  });

  group('Malformed and incomplete math', () {
    for (final text in [
      r'Bad $\frac{a{$ here',
      "\$\$\n\\sqrt{\n\$\$",
      '\\[\n\\unknowncommand{\n\\]',
      r'Bad \(\frac{\) here',
      r'Bad $\unknowncommand{x}$ here',
    ]) {
      testWidgets(text.replaceAll('\n', ' '), (tester) async {
        await _pump(tester, text);

        expect(tester.takeException(), isNull);
        expect(_visible(tester).trim(), isNotEmpty);
        expect(_visible(tester), isNot(contains('ParseException')));
        expect(_visible(tester), isNot(contains('Exception')));
      });
    }

    testWidgets('a malformed equation shows its source as plain text', (tester) async {
      await _pump(tester, r'Bad $\frac{a{$ here');

      expect(_visible(tester), contains(r'\frac{a{'));
    });

    for (final text in [r'$', r'$$', '\$\$\n', r'\(', r'\[', r'\frac{', r'streaming \($', "\$\$\n\\frac{a}"]) {
      testWidgets('incomplete: ${text.replaceAll('\n', '⏎')}', (tester) async {
        await _pump(tester, text, streaming: true);

        expect(tester.takeException(), isNull);
      });
    }
  });

  group('Streaming', () {
    testWidgets('inline math appears once it is complete', (tester) async {
      const frames = [
        r'The derivative is $',
        r'The derivative is $\frac',
        r'The derivative is $\frac{dy}',
        r'The derivative is $\frac{dy}{dx}',
        r'The derivative is $\frac{dy}{dx}$',
      ];
      for (final frame in frames) {
        await _pump(tester, frame, streaming: true);
        expect(tester.takeException(), isNull, reason: frame);
        expect(_visible(tester), contains('The derivative is'), reason: frame);
      }
      expect(_mathCount(), 1);
      expect(_showsDelimiters(tester), isFalse);
    });

    testWidgets('display math appears once it is complete', (tester) async {
      const frames = ['\$', '\$\$', '\$\$\\frac', '\$\$\n\\frac{a}{b}', '\$\$\n\\frac{a}{b}\n\$\$'];
      for (final frame in frames) {
        await _pump(tester, frame, streaming: true);
        expect(tester.takeException(), isNull, reason: frame);
      }
      expect(_mathCount(), 1);
      expect(_showsDelimiters(tester), isFalse);
    });

    testWidgets('the same widget rebuilt with growing text never throws', (tester) async {
      const full = 'Intro \$a^2\$ then\n\n\$\$\n\\int_0^1 x^2 dx\n\$\$\n\nEnd \\(b\\) \\[c\\] `\$x`';
      for (var i = 1; i <= full.length; i++) {
        await _pump(tester, full.substring(0, i), streaming: i < full.length);
        expect(tester.takeException(), isNull, reason: full.substring(0, i));
      }
    });
  });

  group('Layout', () {
    const longEquation =
        '\$\$\nf(x)=a_0+\\sum_{n=1}^{\\infty}\\left(a_n\\cos\\frac{n\\pi x}{L}+b_n\\sin\\frac{n\\pi x}{L}\\right)'
        '+c_0+c_1+c_2+c_3+c_4+c_5+c_6+c_7+c_8+c_9\n\$\$';
    const matrix = '\$\$\n\\begin{bmatrix}1&2&3\\\\4&5&6\\\\7&8&9\\end{bmatrix}\n\$\$';

    for (final width in [640.0, 300.0]) {
      testWidgets('long equation and matrix do not overflow at width $width', (tester) async {
        await _pump(tester, 'Long:\n\n$longEquation\n\nMatrix:\n\n$matrix', width: width);

        expect(tester.takeException(), isNull);
        expect(_mathCount(), 2);
        expect(find.byType(SingleChildScrollView), findsWidgets);
      });
    }
  });

  group('MessageBubble', () {
    testWidgets('renders a real assistant answer with heading, text and equations', (tester) async {
      final message = ChatMessage(
        id: 1,
        role: MessageRole.assistant,
        content:
            '## Chain Rule\n\nFor\n\n\$\$\ny=(2x+3)^5\n\$\$\n\nthe derivative is\n\n'
            '\$\$\n\\frac{dy}{dx}=10(2x+3)^4\n\$\$\n',
        createdAt: '2026-01-01T00:00:00Z',
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: MessageBubble(message: message, onSaveToMemory: () {}),
            ),
          ),
        ),
      );

      expect(_visible(tester), contains('Chain Rule'));
      expect(_visible(tester), contains('the derivative is'));
      expect(_mathCount(), 2);
      expect(_showsDelimiters(tester), isFalse);
      expect(find.text('Save to Learning Memory'), findsOneWidget);
      expect(message.content, contains(r'\frac{dy}{dx}'));
      expect(message.content, contains(r'$$'));
      expect(tester.takeException(), isNull);
    });

    testWidgets('user messages are not rendered as math', (tester) async {
      final message = ChatMessage(
        id: 2,
        role: MessageRole.user,
        content: r'What is $E = mc^2$ and costs $5?',
        createdAt: '2026-01-01T00:00:00Z',
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: MessageBubble(message: message)),
        ),
      );

      expect(_mathCount(), 0);
      expect(find.text(r'What is $E = mc^2$ and costs $5?'), findsOneWidget);
    });
  });
}
