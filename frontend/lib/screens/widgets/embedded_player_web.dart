// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;
import 'dart:ui_web' as ui_web;
import 'package:flutter/material.dart';

final Set<String> _registeredViews = <String>{};
html.AudioElement? _activeAudio;

Widget buildWebIframe({
  required String url,
  required double height,
}) {
  final String viewType = 'bg-spotify-embed-${url.hashCode}';
  if (!_registeredViews.contains(viewType)) {
    _registeredViews.add(viewType);
    ui_web.platformViewRegistry.registerViewFactory(viewType, (int viewId) {
      final html.IFrameElement iframe = html.IFrameElement()
        ..src = url
        ..style.border = 'none'
        ..style.width = '100%'
        ..style.height = '100%'
        ..style.borderRadius = '12px'
        ..allow = 'autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture';
      return iframe;
    });
  }

  return SizedBox(
    height: height,
    width: double.infinity,
    child: HtmlElementView(
      key: ValueKey<String>(viewType),
      viewType: viewType,
    ),
  );
}

void playHtmlAudio(String url) {
  _activeAudio?.pause();
  _activeAudio = html.AudioElement(url)
    ..autoplay = true
    ..play();
}

void pauseHtmlAudio() {
  _activeAudio?.pause();
}
