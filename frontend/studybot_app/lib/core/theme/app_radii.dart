import 'package:flutter/material.dart';

/// Corner-radius scale. Rounded, restrained surfaces — never sharp
/// rectangles, never the exaggerated "bubble" radii of a mobile chat toy.
abstract final class AppRadii {
  static const sm = 8.0;
  static const md = 12.0;
  static const lg = 16.0;
  static const xl = 20.0;
  static const pill = 999.0;

  static const smRadius = BorderRadius.all(Radius.circular(sm));
  static const mdRadius = BorderRadius.all(Radius.circular(md));
  static const lgRadius = BorderRadius.all(Radius.circular(lg));
  static const xlRadius = BorderRadius.all(Radius.circular(xl));
  static const pillRadius = BorderRadius.all(Radius.circular(pill));
}
