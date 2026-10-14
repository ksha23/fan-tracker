# Third-party notices and credits

## Aqara-LANLink (MIT)

`addon/fan_tracker/aqara_app.py` reimplements the Aqara Home app login and
resource queries. Its region servers, app ids and keys, RSA public key,
endpoint paths, client headers and signing rule are taken from
[absent42/Aqara-LANLink](https://github.com/absent42/Aqara-LANLink)
(`hub/cloud_client.py`), which documents them from the Aqara Home app.

```
MIT License

Copyright (c) 2026 Dan Gibson

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Facts used, no code copied

- [MrStrategy/FHEM-AqaraFP2](https://github.com/MrStrategy/FHEM-AqaraFP2):
  resource `4.22.700` is a JSON list of targets with `id`, `x`, `y`,
  `rangeId` and `state`.
- [JameZUK/esphome_fp2_ng](https://github.com/JameZUK/esphome_fp2_ng):
  FP2 radar coordinate ranges and scale (about 800 units per 7 m) and the
  mounting position codes.
- [Darkdragon14/ha-aqara-devices](https://github.com/Darkdragon14/ha-aqara-devices):
  Aqara Open API v3 signing, intents and regional servers, used by
  `addon/fan_tracker/aqara.py`.
- [JeffSteinbok/hass-dreo](https://github.com/JeffSteinbok/hass-dreo):
  the Home Assistant integration that exposes Dreo pan and tilt as `number`
  entities. It is a requirement, not bundled.
