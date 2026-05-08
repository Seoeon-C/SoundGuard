import 'dart:async';
import 'dart:io';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:record/record.dart';
import 'package:path_provider/path_provider.dart';
import 'package:http/http.dart' as http;
import 'package:permission_handler/permission_handler.dart';
import 'package:audioplayers/audioplayers.dart';

const String kServerUrl = "http://168.107.31.37:8000";

void main() => runApp(const MaterialApp(home: SensorApp()));

class SensorApp extends StatefulWidget {
  const SensorApp({super.key});
  @override
  State<SensorApp> createState() => _SensorAppState();
}

class _SensorAppState extends State<SensorApp> {
  final _record = AudioRecorder();
  final _audioPlayer = AudioPlayer();

  bool _isSensing = false;
  bool _isAnnouncing = false;
  bool _isUploading = false;
  String _statusText = "구역을 먼저 설정해 주세요";

  List<Map<String, dynamic>> _zones = [];
  Map<String, dynamic>? _selectedZone;
  bool _loadingZones = false;

  @override
  void initState() {
    super.initState();
    _fetchZones();
  }

  Future<void> _fetchZones() async {
    setState(() => _loadingZones = true);
    try {
      final response = await http
          .get(Uri.parse('$kServerUrl/api/zones'))
          .timeout(const Duration(seconds: 10));
      if (response.statusCode == 200) {
        final List<dynamic> data = jsonDecode(response.body);
        setState(() => _zones = data.cast<Map<String, dynamic>>());
      }
    } catch (e) {
      debugPrint("❌ 구역 목록 로드 오류: $e");
    } finally {
      setState(() => _loadingZones = false);
    }
  }

  void _showZoneSelector() {
    if (_loadingZones) return;
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheetState) => Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 16),
              child: Text(
                "구역 선택",
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
            ),
            const Divider(height: 1),
            if (_zones.isEmpty)
              const Padding(
                padding: EdgeInsets.all(24),
                child: Text("등록된 구역이 없습니다"),
              )
            else
              ConstrainedBox(
                constraints: BoxConstraints(
                  maxHeight: MediaQuery.of(context).size.height * 0.4,
                ),
                child: ListView(
                  shrinkWrap: true,
                  children: _zones.map((zone) {
                    final isSelected = _selectedZone?['id'] == zone['id'];
                    return ListTile(
                      leading: Icon(
                        Icons.location_on,
                        color: isSelected ? Colors.blue : Colors.grey,
                      ),
                      title: Text(zone['name'] ?? zone['id']),
                      subtitle:
                          zone['label'] != null ? Text(zone['label']) : null,
                      selected: isSelected,
                      selectedColor: Colors.blue,
                      onTap: () {
                        setState(() {
                          _selectedZone = zone;
                          _statusText = "감지 대기 중";
                        });
                        Navigator.pop(ctx);
                      },
                    );
                  }).toList(),
                ),
              ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.refresh),
              title: const Text("목록 새로고침"),
              onTap: () {
                Navigator.pop(ctx);
                _fetchZones().then((_) {
                  if (mounted) _showZoneSelector();
                });
              },
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }

void _setStatus(String text) {
    if (mounted) setState(() => _statusText = text);
  }

  String get _deviceId => "${_selectedZone!['id']}_phone1";

  Future<void> _downloadAndPlay(String url) async {
    _isAnnouncing = true;
    try {
      await _audioPlayer.play(UrlSource(url));
      await _audioPlayer.onPlayerComplete.first
          .timeout(const Duration(seconds: 30));
    } catch (e) {
      debugPrint("❌ 재생 오류: $e");
    } finally {
      _isAnnouncing = false;
    }
  }

  Future<void> _uploadAndPlayAnnouncement(String path) async {
    if (_isUploading || _isAnnouncing) {
      final file = File(path);
      if (await file.exists()) await file.delete();
      return;
    }
    _isUploading = true;
    try {
      _setStatus("서버로 전송 중...");

      final request = http.MultipartRequest(
        'POST',
        Uri.parse('$kServerUrl/upload'),
      );
      request.files.add(await http.MultipartFile.fromPath('file', path));
      request.fields['device_id'] = _deviceId;

      final streamedResponse =
          await request.send().timeout(const Duration(seconds: 30));
      final response = await http.Response.fromStream(streamedResponse)
          .timeout(const Duration(seconds: 8)); // 서버 처리 타임아웃

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final String announcementUrl = data['announcement_url'] ?? "";

        if (announcementUrl.isNotEmpty) {
          _setStatus("안내방송 재생 중...");
          await _downloadAndPlay(announcementUrl);
          _setStatus("실시간 감지 중...");
        } else {
          _setStatus("실시간 감지 중...");
        }
      } else {
        _setStatus("서버 응답 오류 (${response.statusCode}) — 재시도 중...");
      }
    } on TimeoutException {
      _setStatus("처리 시간 초과 → 다음 청크로 진행");
      debugPrint("⏱ 서버 응답 타임아웃 (8초 초과), 다음 청크로 진행");
    } catch (e) {
      _setStatus("통신 오류 — 재시도 중...");
      debugPrint("❌ 오류: $e");
    } finally {
      _isUploading = false;
      final file = File(path);
      if (await file.exists()) await file.delete();
    }
  }

  Future<void> _startSensingLoop() async {
    while (_isSensing) {
      final dir = await getTemporaryDirectory();
      final path =
          '${dir.path}/audio_${DateTime.now().millisecondsSinceEpoch}.wav';

      _setStatus("녹음 중...");
      await _record.start(
        const RecordConfig(encoder: AudioEncoder.wav, sampleRate: 16000),
        path: path,
      );

      await Future.delayed(const Duration(seconds: 5));
      await _record.stop();

      if (!_isSensing) {
        final file = File(path);
        if (await file.exists()) await file.delete();
        break;
      }

      if (!_isAnnouncing) {
        await _uploadAndPlayAnnouncement(path);
      } else {
        final file = File(path);
        if (await file.exists()) await file.delete();
      }
    }
  }

  void _toggleSensing() async {
    if (_isSensing) {
      setState(() {
        _isSensing = false;
        _statusText = "감지 중단됨";
      });
      await _record.stop();
      return;
    }

    final status = await Permission.microphone.request();
    if (!status.isGranted) {
      _setStatus("마이크 권한이 필요합니다");
      return;
    }

    setState(() {
      _isSensing = true;
      _statusText = "센서 초기화 중...";
    });

    // 서버 초기 연결 안정화 대기
    await Future.delayed(const Duration(seconds: 3));

    if (!_isSensing) return;

    setState(() {
      _statusText = "실시간 감지 중...";
    });

    _startSensingLoop();
  }

  @override
  void dispose() {
    _record.dispose();
    _audioPlayer.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final zoneSelected = _selectedZone != null;

    return Scaffold(
      appBar: AppBar(
        title: const Text("위기 감지 시스템 (센서)"),
        backgroundColor: Colors.blueGrey,
      ),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              _isSensing ? Icons.mic : Icons.mic_off,
              size: 100,
              color: _isSensing ? Colors.redAccent : Colors.grey,
            ),
            const SizedBox(height: 20),
            Text(
              _statusText,
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.bold,
                color: _isSensing ? Colors.red : Colors.black54,
              ),
            ),
            const SizedBox(height: 8),
            if (zoneSelected) ...[
              Text(
                "구역: ${_selectedZone!['name']}",
                style: const TextStyle(fontSize: 14, color: Colors.blueGrey),
              ),
            ],
            const SizedBox(height: 4),
            Text(
              "서버: $kServerUrl",
              style: const TextStyle(fontSize: 12, color: Colors.grey),
            ),
            const SizedBox(height: 30),
            OutlinedButton.icon(
              onPressed: _isSensing ? null : _showZoneSelector,
              icon: _loadingZones
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.location_on),
              label: Text(zoneSelected ? "구역 변경" : "구역 설정"),
              style: OutlinedButton.styleFrom(
                padding:
                    const EdgeInsets.symmetric(horizontal: 30, vertical: 14),
              ),
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: zoneSelected ? _toggleSensing : null,
              style: ElevatedButton.styleFrom(
                backgroundColor: _isSensing ? Colors.red : Colors.blue,
                disabledBackgroundColor: Colors.grey.shade300,
                padding: const EdgeInsets.symmetric(
                  horizontal: 50,
                  vertical: 20,
                ),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(30),
                ),
              ),
              child: Text(
                _isSensing ? "감지 중단" : "감지 시작",
                style: const TextStyle(color: Colors.white, fontSize: 22),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
