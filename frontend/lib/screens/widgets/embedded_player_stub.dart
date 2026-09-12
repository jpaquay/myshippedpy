import 'package:flutter/material.dart';

Widget buildWebIframe({
  required String url,
  required double height,
}) {
  return SizedBox(
    height: height,
    child: Center(
      child: Text('Embedded web player: $url'),
    ),
  );
}

void playHtmlAudio(String url) {}
void pauseHtmlAudio() {}
