import React, { useEffect, useState } from 'react';
import { ShieldCheck, Activity } from 'lucide-react';

function App() {
  // 1. 필요한 모든 상태(State) 선언
  const [logs, setLogs] = useState([]);
  const [isRecording, setIsRecording] = useState(false);
  const [currentStatus, setCurrentStatus] = useState({ code: 0, label: '대기 중' });

  useEffect(() => {
    let ws;
    
    // 연결을 시도하는 함수
    const connect = () => {
      ws = new WebSocket("ws://localhost:8000/ws");

      ws.onopen = () => console.log("✅ 백엔드와 연결 성공!");

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log("받은 데이터:", data);

        if (data.type === "status") {
          setIsRecording(data.message === "recording");
          return;
        }

        setLogs((prev) => [data, ...prev].slice(0, 20));
        setIsRecording(false);
        
        if (data.situation !== undefined) {
          setCurrentStatus({ 
            code: data.situation, 
            label: data.situation_name || '분석 완료' 
          });
        }
      };

      ws.onerror = (err) => {
        console.error("❌ 연결 에러:", err);
      };

      ws.onclose = () => {
        console.log("🔌 연결이 닫혔습니다. 3초 후 재연결 시도...");
        setTimeout(connect, 3000); // 서버가 죽었을 때 자동으로 다시 붙게 함
      };
    };

    connect();

    // 컴포넌트가 사라질 때 연결 정리
    return () => {
      if (ws) ws.close();
    };
  }, []);

  // 2. 리턴문은 단 하나여야 합니다!
  return (
    <div className={`min-h-screen p-8 font-mono transition-colors duration-500 ${
      currentStatus.code === 2 ? 'bg-red-900 text-white' : 
      currentStatus.code === 1 ? 'bg-orange-900 text-white' : 'bg-gray-900 text-green-400'
    }`}>
      <h1 className="text-3xl font-bold flex items-center gap-2 mb-6">
        <ShieldCheck /> SoundGuard 실시간 모니터링
      </h1>

      {/* 녹음 상태 표시등 */}
      <div className="mb-4 h-6">
        {isRecording && <div className="animate-pulse text-yellow-400">● 현장 소리 녹음 및 AI 분석 중...</div>}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* 상태 요약 판넬 */}
        <div className="bg-black/40 p-6 rounded-lg border border-current">
          <h2 className="text-xl mb-4 flex items-center gap-2">
            <Activity /> 현재 상태: {currentStatus.label}
          </h2>
          {currentStatus.code === 2 && <div className="text-5xl animate-bounce">🚨 EMERGENCY 🚨</div>}
        </div>

        {/* 로그 창 */}
        <div className="bg-black p-4 rounded border border-gray-700 h-[500px] overflow-y-auto text-sm">
          <h3 className="text-gray-500 mb-2 border-b border-gray-800 pb-2">실시간 감지 로그</h3>
          {logs.length === 0 && <div className="text-gray-600 italic">감지된 이벤트가 없습니다.</div>}
          {logs.map((log, i) => (
            <div key={i} className="mb-3 border-b border-gray-800 pb-2">
              <div className="flex justify-between text-xs opacity-50 mb-1">
                <span>[{log.timestamp}]</span>
                <span className={log.situation === 2 ? 'text-red-400' : 'text-green-400'}>
                  위험도: {log.situation}
                </span>
              </div>
              <div>
                <span className="font-bold text-blue-400">[{log.env_label}]</span> {log.reason}
              </div>
              {log.stt_text && <div className="text-yellow-200 mt-1 italic">" {log.stt_text} "</div>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default App;