import 'dart:math' as math;

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import 'media_bubbles.dart' show openVideoPlayer;
import 'template_widgets.dart'; // For ActionCallback

/// Flex Message 渲染（Bubble 與 Carousel，與 Messaging API 格式相容）。
///
/// 支援的元件：box、text、span、image、icon、button、separator、filler、spacer、video。
/// 支援的常用屬性：layout（horizontal / vertical / baseline）、flex、spacing、margin、
/// padding*、backgroundColor、background（linearGradient）、borderColor、borderWidth、
/// cornerRadius、width / height / maxWidth / maxHeight、justifyContent、alignItems、
/// gravity、align、position / offset*、action、size、weight、style、decoration、
/// wrap、maxLines、lineSpacing、aspectRatio、aspectMode、bubble size、direction、styles。
///
/// Flex 卡片的顏色由 Bot 指定，因此卡片底色預設為白色以保持 Bot 設計的可讀性。
class FlexMessageWidget extends StatelessWidget {
  final Map<String, dynamic> flexContents;
  final ActionCallback onAction;

  const FlexMessageWidget({
    super.key,
    required this.flexContents,
    required this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    final renderer = FlexRenderer(context: context, onAction: onAction);
    final type = flexContents['type'] ?? 'bubble';

    if (type == 'carousel') {
      final bubbles = FlexRenderer.mapList(flexContents['contents']);
      // 與 LINE 相同：輪播中的卡片等高，footer 貼齊底部
      return SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.only(right: 12),
        child: IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              for (var i = 0; i < bubbles.length; i++) ...[
                if (i > 0) const SizedBox(width: 10),
                renderer.bubble(bubbles[i], fillHeight: true),
              ],
            ],
          ),
        ),
      );
    }

    // 單張卡片：寬度不超過聊天泡泡可用寬度
    return LayoutBuilder(
      builder: (context, constraints) => renderer.bubble(
        flexContents,
        maxWidth: constraints.maxWidth.isFinite ? constraints.maxWidth : null,
      ),
    );
  }
}

/// 把 Flex JSON 轉成 Flutter Widget。
class FlexRenderer {
  final BuildContext context;
  final ActionCallback onAction;

  FlexRenderer({required this.context, required this.onAction});

  // ==========================================================================
  // 尺寸對照表（單位：邏輯像素）
  // ==========================================================================
  static const Map<String, double> bubbleWidths = {
    'nano': 120, 'micro': 160, 'deca': 220, 'hecto': 241,
    'kilo': 260, 'mega': 300, 'giga': 386,
  };
  static const Map<String, double> spacingSizes = {
    'none': 0, 'xs': 2, 'sm': 4, 'md': 8, 'lg': 12, 'xl': 16, 'xxl': 20,
  };
  static const Map<String, double> radiusSizes = spacingSizes;
  static const Map<String, double> borderWidths = {
    'none': 0, 'light': 0.5, 'normal': 1, 'medium': 2, 'semi-bold': 3, 'bold': 4,
  };
  static const Map<String, double> fontSizes = {
    'xxs': 11, 'xs': 13, 'sm': 14, 'md': 16, 'lg': 19, 'xl': 22,
    'xxl': 29, '3xl': 35, '4xl': 48, '5xl': 74,
  };
  static const Map<String, double> imageSizes = {
    'xxs': 40, 'xs': 60, 'sm': 80, 'md': 100, 'lg': 120, 'xl': 140,
    'xxl': 160, '3xl': 180, '4xl': 200, '5xl': 240,
  };
  static const Color defaultTextColor = Color(0xFF111111);
  static const Color defaultSeparatorColor = Color(0xFFE3E5EE);

  // ==========================================================================
  // 共用工具
  // ==========================================================================
  static Map<String, dynamic>? asMap(dynamic v) =>
      v is Map ? Map<String, dynamic>.from(v) : null;

  static List<Map<String, dynamic>> mapList(dynamic v) => v is List
      ? v.whereType<Map>().map((m) => Map<String, dynamic>.from(m)).toList()
      : <Map<String, dynamic>>[];

  /// 解析 `#RRGGBB` 或 `#RRGGBBAA`（LINE 的透明度放在最後）
  static Color? parseColor(dynamic value) {
    if (value is! String || !value.startsWith('#')) return null;
    final hex = value.substring(1);
    final parsed = int.tryParse(hex, radix: 16);
    if (parsed == null) return null;
    if (hex.length == 6) return Color(0xFF000000 | parsed);
    if (hex.length == 8) {
      final rgb = parsed >> 8;
      final alpha = parsed & 0xFF;
      return Color((alpha << 24) | rgb);
    }
    return null;
  }

  /// 解析 `12px`、`12`、關鍵字；百分比需提供 [percentOf]
  static double? length(dynamic value, {Map<String, double>? keywords, double? percentOf}) {
    if (value == null) return null;
    if (value is num) return value.toDouble();
    final text = value.toString().trim();
    if (keywords != null && keywords.containsKey(text)) return keywords[text];
    if (text.endsWith('px')) return double.tryParse(text.substring(0, text.length - 2));
    if (text.endsWith('%')) {
      final p = double.tryParse(text.substring(0, text.length - 1));
      return (p != null && percentOf != null) ? percentOf * p / 100 : null;
    }
    return double.tryParse(text);
  }

  static Alignment _alignOf(String? align, String? gravity) {
    final x = switch (align) { 'start' => -1.0, 'end' => 1.0, _ => 0.0 };
    final y = switch (gravity) { 'center' => 0.0, 'bottom' => 1.0, _ => -1.0 };
    return Alignment(x, y);
  }

  Widget _tappable(Map<String, dynamic> item, Widget child) {
    final action = asMap(item['action']);
    if (action == null) return child;
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => onAction(action),
        child: child,
      ),
    );
  }

  // ==========================================================================
  // Bubble
  // ==========================================================================
  Widget bubble(Map<String, dynamic> data, {double? maxWidth, bool fillHeight = false}) {
    var width = bubbleWidths[data['size']] ?? bubbleWidths['mega']!;
    if (maxWidth != null) width = math.min(width, maxWidth);

    final styles = asMap(data['styles']) ?? const {};
    final blocks = <Widget>[];
    var index = 0;

    for (final name in const ['header', 'hero', 'body', 'footer']) {
      final block = asMap(data[name]);
      if (block == null) continue;
      final style = asMap(styles[name]) ?? const {};

      if (index > 0 && style['separator'] == true) {
        blocks.add(Container(
          height: 1,
          color: parseColor(style['separatorColor']) ?? defaultSeparatorColor,
        ));
      }

      Widget content;
      if (name == 'hero') {
        content = component(block, parentWidth: width, inHorizontal: false);
      } else {
        // 區塊預設內距（未指定 padding 時）
        final defaultPadding = name == 'footer' ? 10.0 : 16.0;
        content = box(block, parentWidth: width, defaultPadding: defaultPadding);
      }
      final bg = parseColor(style['backgroundColor']);
      if (bg != null) content = ColoredBox(color: bg, child: content);
      if (fillHeight && name == 'body') content = Expanded(child: content);
      blocks.add(content);
      index++;
    }

    Widget result = Container(
      width: width,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: defaultSeparatorColor),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: fillHeight ? MainAxisSize.max : MainAxisSize.min,
        children: blocks,
      ),
    );

    if (data['direction'] == 'rtl') {
      result = Directionality(textDirection: TextDirection.rtl, child: result);
    }
    return _tappable(data, result);
  }

  // ==========================================================================
  // 元件分派
  // ==========================================================================
  Widget component(
    Map<String, dynamic> item, {
    required double? parentWidth,
    required bool inHorizontal,
    bool inBaseline = false,
  }) {
    switch (item['type']) {
      case 'box':
        return box(item, parentWidth: parentWidth);
      case 'text':
        return text(item, inBaseline: inBaseline);
      case 'image':
        return image(item, parentWidth: parentWidth);
      case 'icon':
        return icon(item);
      case 'button':
        return button(item);
      case 'separator':
        final color = parseColor(item['color']) ?? defaultSeparatorColor;
        return inHorizontal
            ? Container(width: 1, color: color)
            : Container(height: 1, color: color);
      case 'video':
        return video(item, parentWidth: parentWidth);
      case 'spacer':
        final size = length(item['size'], keywords: spacingSizes) ?? 8;
        return SizedBox(width: size, height: size);
      case 'filler':
        return const SizedBox.shrink();
      default:
        return const SizedBox.shrink();
    }
  }

  // ==========================================================================
  // Box
  // ==========================================================================
  EdgeInsetsDirectional _padding(Map<String, dynamic> item, double? width, double fallback) {
    final all = length(item['paddingAll'], keywords: spacingSizes, percentOf: width);
    double side(String key) =>
        length(item[key], keywords: spacingSizes, percentOf: width) ?? all ?? fallback;
    return EdgeInsetsDirectional.fromSTEB(
      side('paddingStart'), side('paddingTop'), side('paddingEnd'), side('paddingBottom'),
    );
  }

  Decoration? _boxDecoration(Map<String, dynamic> item) {
    final bg = parseColor(item['backgroundColor']);
    final border = parseColor(item['borderColor']);
    final borderWidth = length(item['borderWidth'], keywords: borderWidths) ?? (border != null ? 1 : 0);
    final radius = length(item['cornerRadius'], keywords: radiusSizes) ?? 0;

    Gradient? gradient;
    final background = asMap(item['background']);
    if (background != null && background['type'] == 'linearGradient') {
      final start = parseColor(background['startColor']) ?? Colors.transparent;
      final end = parseColor(background['endColor']) ?? Colors.transparent;
      final center = parseColor(background['centerColor']);
      final angleText = (background['angle'] ?? '0deg').toString().replaceAll('deg', '');
      final angle = (double.tryParse(angleText) ?? 0) * math.pi / 180;
      // LINE：0deg 由下往上、90deg 由左往右
      final to = Alignment(math.sin(angle), -math.cos(angle));
      final from = Alignment(-to.x, -to.y);
      final centerPos = (length(background['centerPosition']) ?? 50) / 100;
      gradient = LinearGradient(
        begin: from,
        end: to,
        colors: center == null ? [start, end] : [start, center, end],
        stops: center == null ? null : [0, centerPos.clamp(0.0, 1.0), 1],
      );
    }

    if (bg == null && gradient == null && borderWidth == 0 && radius == 0) return null;
    return BoxDecoration(
      color: gradient == null ? bg : null,
      gradient: gradient,
      borderRadius: radius > 0 ? BorderRadius.circular(radius) : null,
      border: borderWidth > 0
          ? Border.all(color: border ?? Colors.black, width: borderWidth)
          : null,
    );
  }

  Widget box(Map<String, dynamic> item, {double? parentWidth, double defaultPadding = 0}) {
    final layout = (item['layout'] ?? 'vertical').toString();
    final horizontal = layout == 'horizontal' || layout == 'baseline';
    final baseline = layout == 'baseline';
    final all = mapList(item['contents']);

    // 內容可用寬度（用來換算百分比）
    final ownWidth = length(item['width'], percentOf: parentWidth) ?? parentWidth;
    final padding = _padding(item, ownWidth, defaultPadding);
    final borderW = length(item['borderWidth'], keywords: borderWidths) ?? 0;
    final innerWidth = ownWidth == null
        ? null
        : math.max(0.0, ownWidth - padding.horizontal - borderW * 2);

    final relative = all.where((c) => c['position'] != 'absolute').toList();
    final absolute = all.where((c) => c['position'] == 'absolute').toList();

    final spacing = length(item['spacing'], keywords: spacingSizes) ?? 0;
    final fixedHeight = length(item['height']);

    // 水平排列時，子元件寬度由 flex 決定，無法換算百分比
    final childWidth = horizontal ? null : innerWidth;

    // 先整理每個子元件：Widget、flex、gravity、前方間距
    final entries = <({Widget widget, bool expand, int flex, String? gravity, double gap})>[];
    final canFlex = horizontal || fixedHeight != null;
    for (var i = 0; i < relative.length; i++) {
      final child = relative[i];
      final type = child['type'];
      final w = _withOffsets(
        child,
        component(child, parentWidth: childWidth, inHorizontal: horizontal, inBaseline: baseline),
      );
      // margin 會取代 spacing（只作用在主軸前方，第一個元件除外）
      final gap = i == 0 ? 0.0 : (length(child['margin'], keywords: spacingSizes) ?? spacing);
      // LINE：水平排列預設 flex = 1、垂直排列預設 0
      final noDefaultFlex = type == 'icon' || type == 'spacer' || type == 'separator';
      final defaultFlex = horizontal && !noDefaultFlex ? 1 : 0;
      final flex = child['flex'] is num ? (child['flex'] as num).toInt() : defaultFlex;
      final expand = canFlex && (flex > 0 || type == 'filler');
      entries.add((
        widget: w,
        expand: expand,
        flex: flex > 0 ? flex : 1,
        gravity: child['gravity']?.toString(),
        gap: gap,
      ));
    }

    List<Widget> assemble({bool alignByGravity = false}) {
      final out = <Widget>[];
      for (final e in entries) {
        if (e.gap > 0) {
          out.add(horizontal ? SizedBox(width: e.gap) : SizedBox(height: e.gap));
        }
        var w = e.widget;
        if (alignByGravity && e.gravity != null) {
          w = Align(alignment: _alignOf('start', e.gravity), child: w);
        }
        out.add(e.expand ? Expanded(flex: e.flex, child: w) : w);
      }
      return out;
    }

    final justify = switch (item['justifyContent']) {
      'center' => MainAxisAlignment.center,
      'flex-end' => MainAxisAlignment.end,
      'space-between' => MainAxisAlignment.spaceBetween,
      'space-around' => MainAxisAlignment.spaceAround,
      'space-evenly' => MainAxisAlignment.spaceEvenly,
      _ => MainAxisAlignment.start,
    };

    Widget content;
    if (horizontal) {
      final gravities = entries.map((e) => e.gravity).toSet();
      final hasSeparator = relative.any((c) => c['type'] == 'separator');
      final cross = switch (item['alignItems']) {
        'center' => CrossAxisAlignment.center,
        'flex-end' => CrossAxisAlignment.end,
        _ => CrossAxisAlignment.start,
      };

      if (baseline) {
        content = Row(
          mainAxisAlignment: justify,
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: assemble(),
        );
      } else if (hasSeparator || gravities.length > 1) {
        // gravity 不一致或有直線分隔：讓子元件等高，再各自對齊
        content = IntrinsicHeight(
          child: Row(
            mainAxisAlignment: justify,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: assemble(alignByGravity: true),
          ),
        );
      } else {
        final rowCross = switch (gravities.isEmpty ? null : gravities.first) {
          'center' => CrossAxisAlignment.center,
          'bottom' => CrossAxisAlignment.end,
          'top' => CrossAxisAlignment.start,
          _ => cross,
        };
        content = Row(
          mainAxisAlignment: justify,
          crossAxisAlignment: rowCross,
          children: assemble(),
        );
      }
    } else {
      final cross = switch (item['alignItems']) {
        'center' => CrossAxisAlignment.center,
        'flex-end' => CrossAxisAlignment.end,
        'flex-start' => CrossAxisAlignment.start,
        _ => CrossAxisAlignment.stretch,
      };
      content = Column(
        mainAxisSize: fixedHeight != null ? MainAxisSize.max : MainAxisSize.min,
        mainAxisAlignment: justify,
        crossAxisAlignment: cross,
        children: assemble(),
      );
    }

    if (absolute.isNotEmpty) {
      content = Stack(
        clipBehavior: Clip.none,
        children: [
          content,
          for (final child in absolute)
            PositionedDirectional(
              top: length(child['offsetTop'], keywords: spacingSizes),
              bottom: length(child['offsetBottom'], keywords: spacingSizes),
              start: length(child['offsetStart'], keywords: spacingSizes),
              end: length(child['offsetEnd'], keywords: spacingSizes),
              child: component(child, parentWidth: null, inHorizontal: false),
            ),
        ],
      );
    }

    final decoration = _boxDecoration(item);
    final Widget result = Container(
      padding: padding,
      decoration: decoration,
      clipBehavior: decoration == null ? Clip.none : Clip.antiAlias,
      width: length(item['width'], percentOf: parentWidth),
      height: fixedHeight,
      constraints: BoxConstraints(
        maxWidth: length(item['maxWidth'], percentOf: parentWidth) ?? double.infinity,
        maxHeight: length(item['maxHeight']) ?? double.infinity,
      ),
      child: content,
    );
    return _tappable(item, result);
  }

  /// position: relative 時的 offset 平移
  Widget _withOffsets(Map<String, dynamic> item, Widget child) {
    if (item['position'] == 'absolute') return child;
    final top = length(item['offsetTop'], keywords: spacingSizes) ?? 0;
    final bottom = length(item['offsetBottom'], keywords: spacingSizes) ?? 0;
    final start = length(item['offsetStart'], keywords: spacingSizes) ?? 0;
    final end = length(item['offsetEnd'], keywords: spacingSizes) ?? 0;
    final dx = start - end;
    final dy = top - bottom;
    if (dx == 0 && dy == 0) return child;
    return Transform.translate(offset: Offset(dx, dy), child: child);
  }

  // ==========================================================================
  // Text / Span
  // ==========================================================================
  TextStyle _textStyle(Map<String, dynamic> item, {TextStyle? base}) {
    final size = length(item['size'], keywords: fontSizes);
    final decoration = switch (item['decoration']) {
      'underline' => TextDecoration.underline,
      'line-through' => TextDecoration.lineThrough,
      _ => null,
    };
    return (base ?? const TextStyle(color: defaultTextColor, fontSize: 16)).copyWith(
      fontSize: size,
      color: parseColor(item['color']),
      fontWeight: item['weight'] == 'bold' ? FontWeight.bold : (item['weight'] == 'regular' ? FontWeight.normal : null),
      fontStyle: item['style'] == 'italic' ? FontStyle.italic : (item['style'] == 'normal' ? FontStyle.normal : null),
      decoration: decoration,
    );
  }

  Widget text(Map<String, dynamic> item, {bool inBaseline = false}) {
    final style = _textStyle(item);
    final fontSize = style.fontSize ?? 16;
    final lineSpacing = length(item['lineSpacing']);
    final effective = lineSpacing == null ? style : style.copyWith(height: (fontSize + lineSpacing) / fontSize);

    final wrap = item['wrap'] == true;
    final maxLines = item['maxLines'] is num && (item['maxLines'] as num) > 0
        ? (item['maxLines'] as num).toInt()
        : null;
    final align = switch (item['align']) {
      'center' => TextAlign.center,
      'end' => TextAlign.end,
      _ => TextAlign.start,
    };

    final spans = mapList(item['contents']);
    final Widget t = spans.isEmpty
        ? Text(
            (item['text'] ?? '').toString(),
            style: effective,
            textAlign: align,
            softWrap: wrap,
            maxLines: wrap ? maxLines : 1,
            overflow: TextOverflow.ellipsis,
          )
        : Text.rich(
            TextSpan(
              style: effective,
              children: [
                for (final s in spans)
                  TextSpan(text: (s['text'] ?? '').toString(), style: _textStyle(s, base: effective)),
              ],
            ),
            textAlign: align,
            softWrap: wrap,
            maxLines: wrap ? maxLines : 1,
            overflow: TextOverflow.ellipsis,
          );
    return _tappable(item, t);
  }

  // ==========================================================================
  // Image / Icon / Video
  // ==========================================================================
  static double _ratio(dynamic value, [double fallback = 1]) {
    if (value is! String || !value.contains(':')) return fallback;
    final parts = value.split(':');
    final w = double.tryParse(parts[0]);
    final h = double.tryParse(parts[1]);
    if (w == null || h == null || w <= 0 || h <= 0) return fallback;
    return w / h;
  }

  Widget _networkImage(String url, BoxFit fit, Color? background) {
    return CachedNetworkImage(
      imageUrl: url,
      fit: fit,
      placeholder: (_, __) => Container(color: background ?? Colors.grey.shade200),
      errorWidget: (_, __, ___) => Container(
        color: Colors.grey.shade300,
        child: const Icon(Icons.image_outlined, color: Colors.grey),
      ),
    );
  }

  Widget image(Map<String, dynamic> item, {double? parentWidth}) {
    final url = (item['url'] ?? '').toString();
    if (url.isEmpty) return const SizedBox.shrink();

    final sizeKey = (item['size'] ?? 'md').toString();
    final ratio = _ratio(item['aspectRatio']);
    final fit = item['aspectMode'] == 'cover' ? BoxFit.cover : BoxFit.contain;
    final bg = parseColor(item['backgroundColor']);

    Widget img = AspectRatio(
      aspectRatio: ratio,
      child: Container(
        color: bg,
        child: _networkImage(url, fit, bg),
      ),
    );

    if (sizeKey != 'full') {
      final w = length(sizeKey, keywords: imageSizes, percentOf: parentWidth) ?? imageSizes['md']!;
      img = SizedBox(width: w, child: img);
      img = Align(
        alignment: _alignOf(item['align']?.toString() ?? 'center', item['gravity']?.toString()),
        heightFactor: 1,
        child: img,
      );
    }
    return _tappable(item, img);
  }

  Widget icon(Map<String, dynamic> item) {
    final url = (item['url'] ?? '').toString();
    final size = length(item['size'], keywords: fontSizes) ?? 16;
    final ratio = _ratio(item['aspectRatio']);
    if (url.isEmpty) return SizedBox(width: size * ratio, height: size);
    return SizedBox(
      width: size * ratio,
      height: size,
      child: _networkImage(url, BoxFit.contain, null),
    );
  }

  Widget video(Map<String, dynamic> item, {double? parentWidth}) {
    final url = (item['url'] ?? '').toString();
    final preview = (item['previewUrl'] ?? '').toString();
    final ratio = _ratio(item['aspectRatio'], 16 / 9);
    return AspectRatio(
      aspectRatio: ratio,
      child: GestureDetector(
        onTap: url.isEmpty ? null : () => openVideoPlayer(context, url),
        child: Stack(
          fit: StackFit.expand,
          children: [
            if (preview.isNotEmpty)
              _networkImage(preview, BoxFit.cover, Colors.black)
            else
              const ColoredBox(color: Colors.black),
            const Center(
              child: Icon(Icons.play_circle_fill_rounded, size: 52, color: Colors.white),
            ),
          ],
        ),
      ),
    );
  }

  // ==========================================================================
  // Button
  // ==========================================================================
  Widget button(Map<String, dynamic> item) {
    final action = asMap(item['action']) ?? const <String, dynamic>{};
    final label = (action['label'] ?? '').toString();
    final style = (item['style'] ?? 'link').toString();
    final height = item['height'] == 'sm' ? 40.0 : 52.0;
    final scheme = Theme.of(context).colorScheme;
    final custom = parseColor(item['color']);

    final Color bg;
    final Color fg;
    switch (style) {
      case 'primary':
        bg = custom ?? scheme.primary;
        fg = Colors.white;
      case 'secondary':
        bg = custom ?? const Color(0xFFDCDFE5);
        fg = defaultTextColor;
      default:
        bg = Colors.transparent;
        fg = custom ?? scheme.primary;
    }

    final buttonWidget = SizedBox(
      height: height,
      child: TextButton(
        style: TextButton.styleFrom(
          backgroundColor: bg,
          foregroundColor: fg,
          padding: const EdgeInsets.symmetric(horizontal: 8),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
        onPressed: action.isEmpty ? null : () => onAction(action),
        child: Text(
          label,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            fontSize: 16,
            fontWeight: style == 'link' ? FontWeight.w600 : FontWeight.w500,
          ),
        ),
      ),
    );

    final gravity = item['gravity']?.toString();
    if (gravity == null) return buttonWidget;
    return Align(alignment: _alignOf('center', gravity), heightFactor: 1, child: buttonWidget);
  }
}
