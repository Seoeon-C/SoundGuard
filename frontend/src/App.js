import React, { useState, useEffect, useRef } from 'react';
import './App.css';

const RISK_COLOR = { low: '#22c55e', medium: '#f97316', high: '#ef4444' };
const RISK_LABEL = { low: '낮음', medium: '중간', high: '높음' };

const SOUND_CATEGORIES = [
  { key: '발소리',  color: '#f97316' },
  { key: '말소리',  color: '#3b82f6' },
  { key: '비명소리', color: '#ef4444' },
  { key: '환경음',  color: '#22c55e' },
];

const TTS_META = {
  INTRUSION_WARN_1: { label: '1차 경고',  ttsLabel: '1차 침입 경고 방송', color: '#f97316' },
  INTRUSION_WARN_2: { label: '2차 경고',  ttsLabel: '2차 침입 경고 방송', color: '#ef4444' },
  EMERGENCY_GUIDE:  { label: '응급 구조', ttsLabel: '응급 구조 안내 방송', color: '#7c3aed' },
  NONE:             { label: '이상없음',  ttsLabel: '방송 없음',          color: '#22c55e' },
};

function getAlertMeta(log) {
  const key = log.decision?.tts_key;
  if (key && TTS_META[key] && key !== 'NONE') return TTS_META[key];
  return log.status?.level > 0
    ? { label: '감지 중', ttsLabel: '방송 없음', color: '#64748b' }
    : TTS_META.NONE;
}

const DWELL_MAX = 30;

function GaugeBar({ value, max = 100, color = '#3b82f6' }) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div className="progress-bar">
      <div className="progress-fill" style={{ width: `${pct}%`, backgroundColor: color }} />
    </div>
  );
}

function App() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("연결 시도 중...");
  const [logs, setLogs] = useState([]);
  const socket = useRef(null);

  useEffect(() => {
    const connect = () => {
      socket.current = new WebSocket("ws://localhost:8000/ws");

      socket.current.onopen = () => {
        setStatus("연결 성공 (관제 중)");
      };

      socket.current.onmessage = (event) => {
        const response = JSON.parse(event.data);
        if (response.type === "data") {
          setData(response);
          setLogs(prev => [response, ...prev].slice(0, 15));
        } else if (response.type === "status") {
          setStatus(response.message === "recording" ? "음성 분석 중..." : "일시 정지");
        }
      };

      socket.current.onclose = () => {
        setStatus("서버 연결 끊김. 재시도 중...");
        setTimeout(connect, 3000);
      };

      socket.current.onerror = () => socket.current.close();
    };

    connect();
    return () => socket.current?.close();
  }, []);

  const sendCommand = (action, key = "") => {
    if (socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(JSON.stringify({ type: "CONTROL", action, key }));
    }
  };

  const riskLevel = data?.decision?.risk_level || 'low';
  const riskColor = RISK_COLOR[riskLevel] || '#22c55e';
  const dwellPct = Math.min(((data?.status?.duration || 0) / DWELL_MAX) * 100, 100);
  const categoryScores = data?.analysis?.category_scores || {};

  return (
    <div className="dashboard">
      <header className="header">
        <h1>🛡️ SoundGuard Control Center</h1>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <span>{status}</span>
          <button className="btn-pause" onClick={() => sendCommand("PAUSE")}>⏸ 감지 일시정지</button>
        </div>
      </header>

      {/* 왼쪽: 상태 */}
      <aside className="card-group">

        {/* 현재 상태 카드 */}
        <div className={`card ${data?.status?.level > 0 ? 'status-critical' : ''}`}>
          <small>현재 상태</small>
          <h2>{data?.status?.name || "정상상황"}</h2>
          <div className="timer">{String(data?.status?.duration || 0).padStart(2, '0')}:00</div>

          {/* 체류 시간 게이지 */}
          <div style={{ marginTop: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', marginBottom: '4px' }}>
              <span>체류 시간</span>
              <span>{data?.status?.duration || 0}s / {DWELL_MAX}s</span>
            </div>
            <GaugeBar
              value={data?.status?.duration || 0}
              max={DWELL_MAX}
              color={dwellPct > 66 ? '#ef4444' : dwellPct > 33 ? '#f97316' : '#3b82f6'}
            />
          </div>

          {/* 경고 단계 배지 */}
          <div style={{ marginTop: '10px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{
              padding: '2px 8px', borderRadius: '12px', fontSize: '0.7rem',
              backgroundColor: data?.status?.warn1_issued ? '#f97316' : '#475569',
              color: '#fff'
            }}>
              {data?.status?.warn1_issued ? '1차 경고 발령됨' : '1차 경고 대기'}
            </span>
            {data?.decision?.emergency_candidate && (
              <span style={{
                padding: '2px 8px', borderRadius: '12px', fontSize: '0.7rem',
                backgroundColor: '#ef4444', color: '#fff'
              }}>
                응급 후보
              </span>
            )}
          </div>
        </div>

        {/* GPT 판단 결과 카드 */}
        <div className="card" style={{ marginTop: '20px' }}>
          <h3>GPT 판단 결과</h3>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
            <span style={{ fontSize: '0.75rem' }}>위험도</span>
            <span style={{
              padding: '2px 10px', borderRadius: '12px', fontSize: '0.75rem',
              backgroundColor: riskColor, color: '#fff', fontWeight: 'bold'
            }}>
              {RISK_LABEL[riskLevel] || '-'}
            </span>
            <span style={{ fontSize: '0.65rem', color: '#94a3b8', marginLeft: 'auto' }}>
              {data?.decision?.source || '-'}
            </span>
          </div>

          <div style={{
            backgroundColor: '#1e293b', borderRadius: '6px',
            padding: '8px', fontSize: '0.72rem', color: '#cbd5e1',
            minHeight: '60px', lineHeight: '1.5'
          }}>
            {data?.decision?.reason || "판단 대기 중..."}
          </div>

          {data?.decision?.send_to_control_room && (
            <div style={{ marginTop: '8px', fontSize: '0.7rem', color: '#3b82f6' }}>
              📡 관제실 전송됨
            </div>
          )}
        </div>

        {/* 소리 분류 분석 */}
        <div className="card" style={{ marginTop: '20px' }}>
          <h3>소리 인식 결과</h3>
          <div style={{ fontSize: '0.7rem', color: '#94a3b8', marginBottom: '10px' }}>
            AI 분류 신뢰도 {data?.analysis?.confidence || 0}%
          </div>
          {SOUND_CATEGORIES.map(({ key, color }) => (
            <div key={key} style={{ marginBottom: '10px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '4px' }}>
                <span>{key}</span>
                <span style={{ color }}>{categoryScores[key] ?? 0}%</span>
              </div>
              <div className="progress-bar">
                <div
                  className="progress-fill"
                  style={{ width: `${categoryScores[key] ?? 0}%`, backgroundColor: color }}
                />
              </div>
            </div>
          ))}
        </div>
      </aside>

      {/* 중앙: 지도 및 실시간 알림 */}
      <main>
        <div className="card" style={{ height: '400px', position: 'relative', display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
          <div style={{ textAlign: 'center', color: '#475569' }}>
            <div className="animate-ping" style={{ width: '20px', height: '200px', position: 'absolute' }} />
            📍 수락산 위험구간 감시 중<br />
            <small>37.5665° N, 126.9780° E</small>
          </div>
        </div>

        <div className="card" style={{ marginTop: '20px', borderLeft: '5px solid #3b82f6' }}>
          <span style={{ color: '#3b82f6', fontWeight: 'bold' }}>📢 안내 메시지:</span>
          <p>{data?.action_msg || "시스템 가동 중입니다."}</p>
        </div>

        {data?.stt_text && (
          <div className="card" style={{ marginTop: '10px', borderLeft: '5px solid #8b5cf6' }}>
            <span style={{ color: '#8b5cf6', fontWeight: 'bold' }}>🎤 STT 인식 결과:</span>
            <p style={{ marginTop: '4px' }}>{data.stt_text}</p>
          </div>
        )}
      </main>

      {/* 오른쪽: 제어 및 로그 */}
      <aside className="card-group">
        <div className="card btn-group">
          <h3>강제 방송 제어</h3>
          <button className="btn-primary" onClick={() => sendCommand("FORCE_TTS", "INTRUSION_WARN_1")}>1차 경고 방송</button>
          <button onClick={() => sendCommand("FORCE_TTS", "EMERGENCY_GUIDE")}>응급 구조 안내</button>
        </div>

        <div className="card" style={{ marginTop: '20px', height: '420px', overflowY: 'auto' }}>
          <h3>이벤트 로그</h3>
          {logs.map((log, i) => {
            const alert = getAlertMeta(log);
            return (
              <div key={i} className="log-item" style={{
                borderLeft: `3px solid ${alert.color}`,
                paddingLeft: '10px',
                marginBottom: '10px',
              }}>
                {/* 타임스탬프 + 경고 단계 배지 */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <span style={{ color: '#64748b', fontSize: '0.68rem' }}>{log.timestamp}</span>
                  <span style={{
                    padding: '2px 8px', borderRadius: '10px', fontSize: '0.68rem',
                    backgroundColor: alert.color, color: '#fff', fontWeight: 'bold',
                  }}>
                    {alert.label}
                  </span>
                </div>

                {/* 상황 이름 */}
                <div style={{ fontWeight: 'bold', fontSize: '0.85rem', marginBottom: '4px' }}>
                  {log.status?.name || '—'}
                </div>

                {/* 방송 내용 */}
                <div style={{ fontSize: '0.72rem', color: '#94a3b8', marginBottom: '3px' }}>
                  🔊 {alert.ttsLabel}
                </div>

                {/* STT 결과 */}
                <div style={{ fontSize: '0.72rem', color: log.stt_text ? '#cbd5e1' : '#475569' }}>
                  🎤 {log.stt_text || '없음'}
                </div>
              </div>
            );
          })}
        </div>
      </aside>
    </div>
  );
}

export default App;
