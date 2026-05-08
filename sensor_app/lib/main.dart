import 'dart:async';
import 'dart:io';
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:record/record.dart';
import 'package:path_provider/path_provider.dart';
import 'package:http/http.dart' as http;
import 'package:permission_handler/permission_handler.dart';
import 'package:audioplayers/audioplayers.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

const String kServerHost = "168.107.31.37:8000";
const String kHttpBase   = "http://$kServerHost";
const String kWsBase     = "ws://$kServerHost";

void main() => runApp(const MaterialApp(home: SensorApp()));

class SensorApp extends StatefulWidget {
  const SensorApp({super.key});
  @override
  State<SensorApp> createState() => _SensorAppState();
}

class _SensorAppState extends State<SensorApp> {
  final _record      = AudioRecorder();
  final _audioPlayer = AudioPlayer();

  // 상태
  bool   _isSensing    = false;
  bool   _isAnnouncing = false;
  bool   _isPaused     = false;
  String _statusText   = "구역을 먼저 설정해 주세요";

  // 구역
  List<Map<String, dynamic>> _zones       = [];
  Map<String, dynamic>?      _selectedZone;
  bool                       _loadingZones = false;

  // WebSocket
  WebSocketChannel? _ws;
  bool              _wsConnected = false;
  StreamSubscription? _wsSub;

  // 청크 스킵 (최신 청크만 전송)
  Uint8List? _pendingChunk;
  bool       _isSendingChunk = false;

  @override
  void initState() {
    super.initState();
    _fetchZones();
  }

  @override
  void dispose() {
    _disconnectWs();
    _record.dispose();
    _audioPlayer.dispose();
    super.dispose();
  }

  // ── 구역 목록 ──────────────────────────────────────────────────

  Future<void> _fetchZones() async {
    setState(() => _loadingZones = true);
    try {
      final response = await http
          .get(Uri.parse('$kHttpBase/api/zones'))
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
              child: Text("구역 선택",
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
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
                      leading: Icon(Icons.location_on,
                          color: isSelected ? Colors.blue : Colors.grey),
                      title: Text(zone['name'] ?? zone['id']),
                      subtitle:
                          zone['label'] != null ? Text(zone['label']) : null,
                      selected: isSelected,
                      selectedColor: Colors.blue,
                      onTap: () {
                        setState(() {
                          _selectedZone = zone;
                          _statusText   = "감지 대기 중";
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

  // ── WebSocket ──────────────────────────────────────────────────

  void _connectWs() {
    final zone = _selectedZone!;
    debugPrint("🔌 WebSocket 연결 시도: $kWsBase/sensor");

    _ws = WebSocketChannel.connect(Uri.parse('$kWsBase/sensor'));

    // zone_info 전송
    _ws!.sink.add(jsonEncode({
      'type':          'zone_info',
      'zone_id':       zone['id'],
      'zone_name':     zone['name'] ?? '알 수 없는 구역',
      'coord':         zone['coord'] ?? '',
      'addr':          zone['label'] ?? '',
      'sample_rate':   16000,
      'chunk_seconds': 5,
    }));

    _wsSub = _ws!.stream.listen(
      (message) {
        if (message is! String) return;
        final data = jsonDecode(message) as Map<String, dynamic>;
        final type = data['type'];

        if (type == 'pause') {
          setState(() => _isPaused = data['paused'] == true);
          _setStatus(_isPaused ? "감지 일시정지" : "실시간 감지 중...");
        } else if (type == 'tts') {
          final url = (data['announcement_url'] ?? '') as String;
          if (url.isNotEmpty && !_isAnnouncing) {
            _setStatus("안내방송 재생 중...");
            _downloadAndPlay(url);
          }
        }
      },
      onDone: () {
        debugPrint("🔌 WebSocket 연결 종료");
        setState(() => _wsConnected = false);
        if (_isSensing) {
          _setStatus("재연결 중...");
          Future.delayed(const Duration(seconds: 3), () {
            if (_isSensing) _connectWs();
          });
        }
      },
      onError: (e) {
        debugPrint("❌ WebSocket 오류: $e");
        setState(() => _wsConnected = false);
        if (_isSensing) {
          Future.delayed(const Duration(seconds: 3), () {
            if (_isSensing) _connectWs();
          });
        }
      },
    );

    setState(() => _wsConnected = true);
    debugPrint("✅ WebSocket 연결됨");
  }

  void _disconnectWs() {
    _wsSub?.cancel();
    _ws?.sink.close();
    _ws = null;
    _wsConnected = false;
  }

  // ── 오디오 재생 ────────────────────────────────────────────────

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
      if (_isSensing && !_isPaused) _setStatus("실시간 감지 중...");
    }
  }

  // ── 청크 전송 (최신 청크만) ────────────────────────────────────

  Future<void> _sendChunkLoop() async {
    while (_isSensing) {
      if (_pendingChunk == null) {
        await Future.delayed(const Duration(milliseconds: 50));
        continue;
      }

      if (_isSendingChunk) {
        // 이미 전송 중 → 대기 (서버가 최신 청크만 처리)
        await Future.delayed(const Duration(milliseconds: 50));
        continue;
      }

      final chunk = _pendingChunk!;
      _pendingChunk = null;
      _isSendingChunk = true;

      try {
        _ws?.sink.add(chunk);
        debugPrint("📤 청크 전송 (${chunk.length} bytes)");
      } catch (e) {
        debugPrint("❌ 청크 전송 오류: $e");
      } finally {
        _isSendingChunk = false;
      }
    }
  }

  // ── 녹음 루프 ──────────────────────────────────────────────────

  Future<void> _startSensingLoop() async {
    // 청크 전송 루프 병렬 실행
    _sendChunkLoop();

    while (_isSensing) {
      if (_isPaused) {
        await Future.delayed(const Duration(milliseconds: 200));
        continue;
      }

      final dir  = await getTemporaryDirectory();
      final path = '${dir.path}/audio_${DateTime.now().millisecondsSinceEpoch}.wav';

      _setStatus("녹음 중...");
      await _record.start(
        const RecordConfig(encoder: AudioEncoder.wav, sampleRate: 16000),
        path: path,
      );

      await Future.delayed(const Duration(seconds: 5));
      await _record.stop();

      if (!_isSensing) {
        final f = File(path);
        if (await f.exists()) await f.delete();
        break;
      }

      if (!_isAnnouncing) {
        final bytes = await File(path).readAsBytes();
        // 최신 청크로 교체 (이전 미전송 청크 버림)
        if (_pendingChunk != null) {
          debugPrint("⏭ 구 청크 버림 → 최신 청크로 교체");
        }
        _pendingChunk = bytes;
        if (!_isPaused) _setStatus("실시간 감지 중...");
      }

      final f = File(path);
      if (await f.exists()) await f.delete();
    }
  }

  // ── 감지 시작/중단 ─────────────────────────────────────────────

  void _toggleSensing() async {
    if (_isSensing) {
      setState(() {
        _isSensing   = false;
        _statusText  = "감지 중단됨";
        _isPaused    = false;
      });
      await _record.stop();
      _disconnectWs();
      return;
    }

    final status = await Permission.microphone.request();
    if (!status.isGranted) {
      _setStatus("마이크 권한이 필요합니다");
      return;
    }

    setState(() {
      _isSensing  = true;
      _statusText = "서버 연결 중...";
    });

    _connectWs();
    await Future.delayed(const Duration(seconds: 2));
    if (!_isSensing) return;

    setState(() => _statusText = "실시간 감지 중...");
    _startSensingLoop();
  }

  void _setStatus(String text) {
    if (mounted) setState(() => _statusText = text);
  }

  // ── UI ────────────────────────────────────────────────────────

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
            if (zoneSelected)
              Text(
                "구역: ${_selectedZone!['name']}",
                style: const TextStyle(fontSize: 14, color: Colors.blueGrey),
              ),
            const SizedBox(height: 4),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  _wsConnected ? Icons.wifi : Icons.wifi_off,
                  size: 14,
                  color: _wsConnected ? Colors.green : Colors.grey,
                ),
                const SizedBox(width: 4),
                Text(
                  _wsConnected ? "연결됨" : "연결 끊김",
                  style: TextStyle(
                    fontSize: 12,
                    color: _wsConnected ? Colors.green : Colors.grey,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              "서버: $kServerHost",
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
