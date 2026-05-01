import { useState, useEffect, useRef, useCallback } from "react"
const VWORLD_KEY = import.meta.env.VITE_VWORLD_KEY
console.log("VWORLD_KEY:", VWORLD_KEY)
/* ─── 상수 ──────────────────────────────────────────────── */
const C = {
  bg:"#07101f", sf:"#0c1828", card:"#101f33", bd:"#162c44", bd2:"#1b3550",
  t1:"#deeaff", t2:"#7090ae", t3:"#2d4a62",
  green:"#34d399", amber:"#fbbf24", red:"#f87171", cyan:"#22d3ee", violet:"#a78bfa",
}

const STATUS_DATA = {
  0:{ c:C.green, bg:"rgba(52,211,153,.09)",  bd:"rgba(52,211,153,.25)",  ico:"✓", tag:"현재 상태 · 정상",  name:"정상",    desc:"구역이 정상적으로 관리 중입니다" },
  1:{ c:C.amber, bg:"rgba(251,191,36,.09)",  bd:"rgba(251,191,36,.25)",  ico:"!", tag:"현재 상태 · 경고",  name:"무단침입", desc:"비허가 인원 진입 감지 — 경고 방송 송출 중" },
  2:{ c:C.red,   bg:"rgba(248,113,113,.09)", bd:"rgba(248,113,113,.25)", ico:"⚠", tag:"현재 상태 · 긴급", name:"위험 감지", desc:"위험 상황 감지 — 즉각 대응 필요" },
}

const LOG_COLORS = {
  sys:{ c:C.cyan,  label:"시스템" },
  n:  { c:C.green, label:"정상"   },
  1:  { c:C.amber, label:"무단침입" },
  2:  { c:C.red,   label:"위험감지" },
  warn:{ c:C.amber, label:"경고방송" },
  emg: { c:C.red,   label:"응급방송" },
  voice:{ c:C.violet, label:"음성" },
}

const DEFAULT_MSGS = {
  w1: "무단 침입이 감지되었습니다. 즉시 퇴거하지 않을 시 관계기관에 신고 조치됩니다.",
  w2: "귀하의 위치 정보가 관계기관에 전송되었습니다. 즉시 이 구역을 이탈하십시오.",
  emg:"위험 상황이 감지되었습니다. 신속히 대피하시고 119에 신고하여 주십시오.",
}

const fmt = s => `${String(Math.floor(s/60)).padStart(2,"0")}:${String(s%60).padStart(2,"0")}`
const nowStr = () => { const d=new Date(); return [d.getHours(),d.getMinutes(),d.getSeconds()].map(v=>String(v).padStart(2,"0")).join(":") }

/* ─── 공통 인라인 스타일 ─────────────────────────────────── */
const inputSt = { width:"100%", background:"#060e1c", border:`1px solid ${C.bd2}`, borderRadius:6, padding:"9px 12px", color:C.t1, fontSize:13, outline:"none", fontFamily:"inherit", transition:"border-color .15s", boxSizing:"border-box" }
const labelSt = { display:"block", fontSize:9, textTransform:"uppercase", letterSpacing:".12em", color:C.t3, fontWeight:700, marginBottom:5 }
const btnCyanSt = { background:C.cyan, color:"#040d19", border:"none", borderRadius:7, padding:"11px 16px", fontSize:13, fontWeight:800, cursor:"pointer", width:"100%", fontFamily:"inherit" }
const tbtnSt = { background:"none", border:"none", color:C.t2, fontSize:11, cursor:"pointer", padding:"4px 8px", borderRadius:4, fontFamily:"inherit" }
const mcHeadSt = { padding:"7px 12px", borderBottom:`1px solid ${C.bd}`, display:"flex", alignItems:"center", justifyContent:"space-between" }
const mctSt = { fontSize:9, textTransform:"uppercase", letterSpacing:".13em", color:C.t3, fontWeight:700 }

/* ════════════════════════════════════════════════════════════
   메인 컴포넌트
════════════════════════════════════════════════════════════ */
export default function SoundGuardDashboard() {
  const [screen, setScreen] = useState("login")  // "login" | "config" | "main"
  const [adminId, setAdminId] = useState("")
  const [config, setConfig] = useState({ zone:"", w1:"", w2:"", emg:"" })
  const SERVER_IP = "192.168.1.100:8000"

  const go = useCallback((scr, cfg) => {
    if (cfg) setConfig(cfg)
    setScreen(scr)
  }, [])

  return (
    <div style={{ minHeight:"100vh", background:C.bg, color:C.t1, fontFamily:"-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif", fontSize:13 }}>
      {screen === "login"  && <LoginScreen  onLogin={id => { setAdminId(id); setScreen("main") }} />}
      {screen === "config" && <ConfigScreen adminId={adminId} initConfig={config} onSave={cfg => go("main", cfg)} onBack={() => setScreen("main")} />}
      {screen === "main"   && <MainScreen   adminId={adminId} config={config} serverIP={SERVER_IP} onGoConfig={() => setScreen("config")} onLogout={() => { setAdminId(""); setScreen("login") }} onUpdateConfig={(cfg)=>setConfig(cfg)} />}
    </div>
  )
}

/* ════════════════════════════════════════════════════════════
   SCREEN 1: 로그인
════════════════════════════════════════════════════════════ */
function LoginScreen({ onLogin }) {
  const [id, setId] = useState("")
  const [pw, setPw] = useState("")
  const [showPw, setShowPw] = useState(false)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  const handle = () => {
    if (!id || !pw) { setError("아이디와 비밀번호를 입력하세요"); return }
    setLoading(true)
    setTimeout(() => {
      if (id === "admin" && pw === "1234") { onLogin(id) }
      else { setError("아이디 또는 비밀번호가 올바르지 않습니다"); setLoading(false) }
    }, 600)
  }

  return (
    <div style={{ display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", minHeight:"100vh", padding:24 }}>
      <div style={{ width:"100%", maxWidth:390 }}>
        {/* 브랜드 */}
        <div style={{ textAlign:"center", marginBottom:28 }}>
          <div style={{ width:70, height:70, borderRadius:18, background:"rgba(34,211,238,.09)", border:"1px solid rgba(34,211,238,.22)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:30, margin:"0 auto 16px" }}>🔊</div>
          <div style={{ fontSize:9, letterSpacing:".2em", textTransform:"uppercase", color:C.t3, marginBottom:7 }}>Sound Guard System</div>
          <div style={{ fontSize:20, fontWeight:800, letterSpacing:"-.02em" }}>음향 기반 위험 예방·구조 시스템</div>
          <div style={{ fontSize:11, color:C.t2, marginTop:5 }}>상황실 관리자 전용</div>
        </div>

        {/* 카드 */}
        <div style={{ background:C.card, border:`1px solid ${C.bd2}`, borderRadius:12, padding:26 }}>
          <div style={{ fontSize:14, fontWeight:800, marginBottom:20 }}>관리자 로그인</div>

          <div style={{ marginBottom:14 }}>
            <label style={labelSt}>관리자 ID</label>
            <input style={inputSt} type="text" placeholder="admin" value={id} onChange={e=>setId(e.target.value)} onKeyDown={e=>e.key==="Enter"&&handle()} />
          </div>

          <div style={{ marginBottom:20, position:"relative" }}>
            <label style={labelSt}>비밀번호</label>
            <input style={{...inputSt, paddingRight:52}} type={showPw?"text":"password"} placeholder="••••••••" value={pw} onChange={e=>setPw(e.target.value)} onKeyDown={e=>e.key==="Enter"&&handle()} />
            <button onClick={()=>setShowPw(!showPw)} style={{ position:"absolute", right:10, bottom:10, background:"none", border:"none", color:C.t3, cursor:"pointer", fontSize:11, padding:4 }}>{showPw?"숨김":"표시"}</button>
          </div>

          {error && <div style={{ background:"rgba(248,113,113,.07)", border:"1px solid rgba(248,113,113,.22)", borderRadius:6, padding:"7px 11px", fontSize:11, color:C.red, marginBottom:12 }}>{error}</div>}

          <button style={{ ...btnCyanSt, opacity:loading?0.6:1 }} onClick={handle} disabled={loading}>
            {loading ? "인증 중..." : "로그인"}
          </button>

          <div style={{ marginTop:13, padding:8, background:"rgba(255,255,255,.025)", borderRadius:5, fontSize:10, color:C.t3, textAlign:"center" }}>
            데모 계정: ID <span style={{color:C.t2,fontWeight:700}}>admin</span> / PW <span style={{color:C.t2,fontWeight:700}}>1234</span>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ════════════════════════════════════════════════════════════
   SCREEN 2: 멘트 설정
════════════════════════════════════════════════════════════ */
function ConfigScreen({ adminId, initConfig, onSave, onBack }) {
  const [zone, setZone] = useState(initConfig.zone || "")
  const [w1,   setW1]   = useState(initConfig.w1   || "")
  const [w2,   setW2]   = useState(initConfig.w2   || "")
  const [emg,  setEmg]  = useState(initConfig.emg  || "")

  const z  = zone.trim() || "[구역명]"
  const pfx = `이곳은 ${z} 입니다.`
  const pv1 = `${pfx} ${w1.trim() || "[1차 경고 멘트]"}`
  const pv2 = `${pfx} ${w2.trim() || "[2차 경고 멘트]"}`
  const pvE = emg.trim() || "[응급 상황 안내 멘트]"

  const save = () => {
    if (!zone.trim()) { alert("구역명을 입력해주세요"); return }
    onSave({ zone: zone.trim(), w1: w1.trim(), w2: w2.trim(), emg: emg.trim() })
  }

  const secSt = { background:C.card, border:`1px solid ${C.bd2}`, borderRadius:10, padding:18, marginBottom:14 }
  const hdSt  = { fontSize:10, fontWeight:800, textTransform:"uppercase", letterSpacing:".1em", color:C.t3, marginBottom:12, display:"flex", alignItems:"center", gap:7 }
  const numSt = (bg=C.cyan) => ({ width:18, height:18, borderRadius:"50%", display:"flex", alignItems:"center", justifyContent:"center", fontSize:9, fontWeight:800, background:bg, color:"#040d19", flexShrink:0 })
  const exSt  = { background:"rgba(255,255,255,.025)", border:`1px solid ${C.bd}`, borderRadius:5, padding:"8px 11px", fontSize:11, color:C.t2, marginBottom:9, lineHeight:1.6 }
  const pvSt  = { background:"rgba(34,211,238,.05)", border:"1px solid rgba(34,211,238,.15)", borderRadius:5, padding:"8px 11px", fontSize:11, color:C.cyan, marginTop:8, lineHeight:1.7 }
  const tagSt = { fontSize:8, color:C.t3, background:"rgba(255,255,255,.04)", padding:"2px 7px", borderRadius:3, fontWeight:400, textTransform:"none", letterSpacing:".04em" }
  const txSt  = { ...inputSt, resize:"vertical", lineHeight:1.6, minHeight:72 }

  return (
    <div style={{ display:"flex", flexDirection:"column", minHeight:"100vh" }}>
      {/* 헤더 */}
      <div style={{ display:"flex", alignItems:"center", gap:10, padding:"10px 22px", borderBottom:`1px solid ${C.bd}`, background:"rgba(10,20,40,.95)", position:"sticky", top:0, zIndex:20 }}>
        <div style={{ fontSize:14, fontWeight:800 }}>🔊 SoundGuard</div>
        <div style={{ fontSize:10, color:C.t3, padding:"2px 8px", background:"rgba(255,255,255,.04)", borderRadius:4 }}>안내 멘트 설정</div>
        <div style={{ marginLeft:"auto", display:"flex", alignItems:"center", gap:8 }}>
          <span style={{ fontSize:10, color:C.t2, padding:"2px 8px", border:`1px solid ${C.bd}`, borderRadius:20 }}>{adminId}</span>
          <button style={tbtnSt} onClick={onBack}>← 메인으로</button>
        </div>
      </div>

      {/* 바디 */}
      <div style={{ maxWidth:660, margin:"0 auto", padding:"28px 22px" }}>
        <h1 style={{ fontSize:20, fontWeight:800, letterSpacing:"-.02em", marginBottom:5 }}>안내 멘트 설정</h1>
        <p style={{ fontSize:12, color:C.t2, marginBottom:24, lineHeight:1.7 }}>상황별로 현장에 송출될 음성 메시지를 설정하세요. 1·2차 경고 멘트는 구역명이 자동으로 앞에 붙습니다.</p>

        {/* 구역명 */}
        <div style={secSt}>
          <div style={hdSt}><span style={numSt()}>1</span> 관리 구역명</div>
          <div style={exSt}><div style={{ fontSize:8, textTransform:"uppercase", letterSpacing:".1em", color:C.t3, marginBottom:3, fontWeight:700 }}>입력 예시</div>강변 저수지 위험구역 &nbsp;/&nbsp; 폐공사장 A구역 &nbsp;/&nbsp; 사유지 출입금지 구역</div>
          <div style={{ marginBottom:9 }}><label style={labelSt}>구역명</label><input style={inputSt} type="text" placeholder="예: 강변 저수지 위험구역" value={zone} onChange={e=>setZone(e.target.value)} /></div>
          <div style={pvSt}><div style={{ fontSize:8, textTransform:"uppercase", letterSpacing:".1em", color:"rgba(34,211,238,.4)", marginBottom:3, fontWeight:700 }}>첫 멘트 자동 생성</div>이곳은 <u>{z}</u> 입니다.</div>
        </div>

        {/* 1차 경고 */}
        <div style={secSt}>
          <div style={hdSt}><span style={numSt(C.amber)}>2</span> 1차 경고 멘트 <span style={tagSt}>5초 이상 체류 감지 시</span></div>
          <div style={exSt}><div style={{ fontSize:8, textTransform:"uppercase", letterSpacing:".1em", color:C.t3, marginBottom:3, fontWeight:700 }}>작성 예시</div>{DEFAULT_MSGS.w1}</div>
          <div style={{ marginBottom:9 }}>
            <label style={labelSt}>앞에 자동 삽입: <span style={{color:C.cyan}}>"{pfx}"</span></label>
            <textarea style={txSt} placeholder="이후 경고 문구를 입력하세요..." rows={3} value={w1} onChange={e=>setW1(e.target.value)} />
          </div>
          <div style={pvSt}><div style={{ fontSize:8, textTransform:"uppercase", letterSpacing:".1em", color:"rgba(34,211,238,.4)", marginBottom:3, fontWeight:700 }}>전체 송출 메시지 미리보기</div>{pv1}</div>
        </div>

        {/* 2차 경고 */}
        <div style={secSt}>
          <div style={hdSt}><span style={numSt(C.red)}>3</span> 2차 경고 멘트 <span style={tagSt}>15초 이상 체류 감지 시</span></div>
          <div style={exSt}><div style={{ fontSize:8, textTransform:"uppercase", letterSpacing:".1em", color:C.t3, marginBottom:3, fontWeight:700 }}>작성 예시</div>{DEFAULT_MSGS.w2}</div>
          <div style={{ marginBottom:9 }}>
            <label style={labelSt}>앞에 자동 삽입: <span style={{color:C.cyan}}>"{pfx}"</span></label>
            <textarea style={txSt} placeholder="이후 경고 문구를 입력하세요..." rows={3} value={w2} onChange={e=>setW2(e.target.value)} />
          </div>
          <div style={pvSt}><div style={{ fontSize:8, textTransform:"uppercase", letterSpacing:".1em", color:"rgba(34,211,238,.4)", marginBottom:3, fontWeight:700 }}>전체 송출 메시지 미리보기</div>{pv2}</div>
        </div>

        {/* 응급 */}
        <div style={secSt}>
          <div style={hdSt}><span style={numSt(C.violet)}>4</span> 응급 상황 안내 멘트 <span style={tagSt}>위험 감지 시</span></div>
          <div style={exSt}><div style={{ fontSize:8, textTransform:"uppercase", letterSpacing:".1em", color:C.t3, marginBottom:3, fontWeight:700 }}>작성 예시</div>{DEFAULT_MSGS.emg}</div>
          <div style={{ marginBottom:9 }}>
            <textarea style={txSt} placeholder="응급 상황 안내 문구를 입력하세요..." rows={3} value={emg} onChange={e=>setEmg(e.target.value)} />
          </div>
          <div style={pvSt}><div style={{ fontSize:8, textTransform:"uppercase", letterSpacing:".1em", color:"rgba(34,211,238,.4)", marginBottom:3, fontWeight:700 }}>전체 송출 메시지 미리보기</div>{pvE}</div>
        </div>

        <button style={{ ...btnCyanSt, padding:13, fontSize:14, marginTop:6 }} onClick={save}>저장 후 모니터링 시작 →</button>
      </div>
    </div>
  )
}

/* ════════════════════════════════════════════════════════════
   모달 컴포넌트: 멘트 수정 전용 오버레이
════════════════════════════════════════════════════════════ */
function MentEditOverlay({ config, onUpdateConfig, onClose, wsRef }) {
  const [w1, setW1] = useState(config.w1)
  const [w2, setW2] = useState(config.w2)
  const [emg, setEmg] = useState(config.emg)

  const save = () => {
    const next = {
      ...config,
      w1: (w1 || "").trim(),
      w2: (w2 || "").trim(),
      emg: (emg || "").trim(),
    }

    onUpdateConfig(next)

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: "tts_config",
        w1: next.w1,
        w2: next.w2,
        emg: next.emg,
      }))
    }

    onClose()
  }

  return (
    <div style={{ background:C.bg, width:600, maxHeight:"90vh", overflowY:"auto", borderRadius:12, border:`1px solid ${C.bd2}`, display:"flex", flexDirection:"column" }}>
      <div style={{ padding:"16px 20px", borderBottom:`1px solid ${C.bd}`, background:C.sf, display:"flex", justifyContent:"space-between", alignItems:"center", position:"sticky", top:0, zIndex:10 }}>
        <div style={{ fontSize:16, fontWeight:800, color:C.cyan }}>🚨 수정 창 🚨</div>
        <button style={tbtnSt} onClick={onClose}>✕ 닫기</button>
      </div>
      <div style={{ padding:"24px" }}>
        <div style={{ marginBottom:16 }}>
          <label style={labelSt}>1차 경고 멘트 수정</label>
          <textarea style={{...inputSt, minHeight:72, resize:"vertical"}} value={w1} onChange={e=>setW1(e.target.value)} />
        </div>
        <div style={{ marginBottom:16 }}>
          <label style={labelSt}>2차 경고 멘트 수정</label>
          <textarea style={{...inputSt, minHeight:72, resize:"vertical"}} value={w2} onChange={e=>setW2(e.target.value)} />
        </div>
        <div style={{ marginBottom:24 }}>
          <label style={labelSt}>위험 감지 응급 멘트 수정</label>
          <textarea style={{...inputSt, minHeight:72, resize:"vertical"}} value={emg} onChange={e=>setEmg(e.target.value)} />
        </div>
        <button style={btnCyanSt} onClick={save}>수정 내용 적용하기</button>
      </div>
    </div>
  )
}

/* ════════════════════════════════════════════════════════════
   SCREEN 3: 메인 대시보드
════════════════════════════════════════════════════════════ */
function MainScreen({ adminId, config, serverIP, onGoConfig, onLogout, onUpdateConfig }) {
  const [status,   setStatus]   = useState(0)
  const [paused,   setPaused]   = useState(false)
  const [detected, setDetected] = useState(false)
  const [elapsed,  setElapsed]  = useState(0)
  const [personEl, setPersonEl] = useState(0)
  const [beats,    setBeats]    = useState({ background:99, loud_noise:1, intrusion:0, emergency:0, impact_noise:0 })
  const [beatsTs,  setBeatsTs]  = useState("—")
  const [lastSnd,  setLastSnd]  = useState("—")
  const [curMsg,   setCurMsg]   = useState(null)
  const [logs,     setLogs]     = useState([])
  const [clock,    setClock]    = useState(nowStr())
  const wsRef = useRef(null)
  const reconnectRef = useRef(null)

  // 팝업 상태들
  const [mentPopup, setMentPopup] = useState(false)
  const [mentEditModal, setMentEditModal] = useState(false)
  const [zoneModal, setZoneModal] = useState(false)
  const [mapInfoModal, setMapInfoModal] = useState(false)

  const [mapCoord, setMapCoord] = useState("37.5665° N, 126.9780° E")
  const [mapAddr, setMapAddr] = useState(config.zone || "관할 구역 주소 미상")
  // 신규: 설정 팝업, 알림 패널
  const [settingsModal, setSettingsModal] = useState(false)
  const [notifPanelOpen, setNotifPanelOpen] = useState(false)
  const [notifications, setNotifications] = useState([])
  const [selfCheckRunning, setSelfCheckRunning] = useState(false)
  const [selfCheckResult, setSelfCheckResult] = useState(null)

  const statusRef  = useRef(status)
  const pausedRef  = useRef(paused)
  const configRef  = useRef(config)
  const adminRef   = useRef(adminId)
  const selectedZoneIdRef = useRef(null)
  const mapCoordRef = useRef(mapCoord)
  const mapAddrRef = useRef(mapAddr)
  const zonesRef = useRef([])
  statusRef.current = status; pausedRef.current = paused
  configRef.current = config; adminRef.current  = adminId
  mapCoordRef.current = mapCoord
  mapAddrRef.current = mapAddr
  

  const startTime = useRef(nowStr())
  /* 구역 */
  const [zones, setZones] = useState([
    {
      id: crypto.randomUUID(),
      name: "관악산 출입통제 구역",
      coord: "37.5665° N, 126.9780° E",
      addr: "관악산 출입통제 구역",
    },
    {
      id: crypto.randomUUID(),
      name: "강변 저수지 위험구역",
      coord: "37.5665° N, 127.9780° E",
      addr: "강변 저수지",
    },
    {
      id: crypto.randomUUID(),
      name: "폐공사장 A구역",
      coord: "37.0000° N, 127.0000° E",
      addr: "폐공사장 A구역",
    },
  ])

  const [selectedZoneId, setSelectedZoneId] = useState(null)

  const [newZoneName, setNewZoneName] = useState("")
  const [newZoneCoord, setNewZoneCoord] = useState("37.5665° N, 126.9780° E")
  const [newZoneAddr, setNewZoneAddr] = useState("")

  selectedZoneIdRef.current = selectedZoneId
  zonesRef.current = zones

  /* 구역 선택*/
  const selectZone = (zone) => {
    setSelectedZoneId(zone.id)

    onUpdateConfig({
      ...configRef.current,
      zone: zone.name,
    })

    setMapCoord(zone.coord)
    setMapAddr(zone.addr)

    addLog("sys", "구역 변경", zone.name)
  }

  /*구역 추가 함수*/
  const addZone = () => {
    const name = newZoneName.trim()
    const coord = newZoneCoord.trim()
    const addr = newZoneAddr.trim() || name

    if (!name) return

    const next = {
      id: crypto.randomUUID(),
      name,
      coord,
      addr,
    }

    setZones((prev) => [...prev, next])
    selectZone(next)

    setNewZoneName("")
    setNewZoneCoord("37.5665° N, 126.9780° E")
    setNewZoneAddr("")
  }
  /*구역 삭제 함수*/
  const deleteZone = (id) => {
    const nextZones = zones.filter((z) => z.id !== id)
    setZones(nextZones)

    if (selectedZoneId === id) {
      const nextZone = nextZones[0]

      if (nextZone) {
        selectZone(nextZone)
      } else {
        setSelectedZoneId(null)
        onUpdateConfig({
          ...configRef.current,
          zone: "",
        })
        setMapCoord("37.5665° N, 126.9780° E")
        setMapAddr("관할 구역 주소 미상")
      }
    }
  }

  /* 시계 */
  useEffect(() => {
    const iv = setInterval(() => setClock(nowStr()), 1000)
    return () => clearInterval(iv)
  }, [])

  /* 타이머 */
  useEffect(() => {
    const iv = setInterval(() => {
      if (pausedRef.current) return
      if (statusRef.current !== 0) setElapsed(p => p + 1)
      if (detected) setPersonEl(p => p + 1)
    }, 1000)
    return () => clearInterval(iv)
  }, [detected])

  /* 초기 로그 */
  useEffect(() => {
    addLog("sys", "시스템 시작", `관리자 ${adminId} 접속 · 모니터링 시작`)
  }, [])

  

  const addLog = useCallback((type, title, detail) => {
    const t = nowStr()
    setLogs(p => [{ id:Date.now()+Math.random(), t, type, title, detail }, ...p].slice(0, 100))
  }, [])
  const sendTtsConfig = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      const cfg = configRef.current
      wsRef.current.send(JSON.stringify({
        type: "tts_config",
        w1: cfg.w1 || "",
        w2: cfg.w2 || "",
        emg: cfg.emg || "",
      }))
    }
  }, [])

  useEffect(() => {
    let closed = false

    const connect = () => {
      const ws = new WebSocket("ws://localhost:8000/ws")
      wsRef.current = ws

      ws.onopen = () => {
        console.log("✅ 서버 연결 성공")
        addLog("sys", "백엔드 연결 성공", "ws://localhost:8000/ws")
        sendTtsConfig()
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        console.log("📡 서버 데이터:", data)

        if (data.type === "status") {
          if (data.message === "paused") setPaused(true)
          return
        }

        if (data.type === "pause_state") {
          setPaused(Boolean(data.paused))
          addLog("sys", data.paused ? "감지 일시정지 적용" : "감지 재개 적용", "백엔드 반영 완료")
          return
        }
        if (data.type === "self_check_result") {
          setSelfCheckRunning(false)
          setSelfCheckResult(data.items || [])
          addLog("sys", "자가진단 완료", "백엔드 점검 결과 수신")
          return
        }
        if (data.type !== "analysis") return

        const situation = Number(data.situation ?? 0)
        setStatus(situation)
        setBeatsTs(data.timestamp || nowStr())
        setBeats(data.beats || {
          background: situation === 0 ? 90 : 5,
          loud_noise: 0,
          intrusion: situation === 1 ? 80 : 0,
          emergency: situation === 2 ? 80 : 0,
          impact_noise: 0,
        })
        const activeZone = zonesRef.current.find(z => z.id === selectedZoneIdRef.current)
        const activeZoneName = activeZone?.name || configRef.current.zone || "관리구역 미지정"
        const activeZoneCoord = activeZone?.coord || mapCoordRef.current
        const activeZoneAddr = activeZone?.addr || mapAddrRef.current
        setLastSnd(data.stt_text?.trim() ? "speech" : (data.beats_raw_label || data.beats_label || "—"))

        let eventTitle = data.situation_name || "분석 결과"
        let noticeKind = null
        let noticeType = situation

        if (data.tts_key === "INTRUSION_WARN_1") {
          eventTitle = "무단침입 - 1차 경고 방송"
          noticeKind = "warn1"
          noticeType = 1
        } else if (data.tts_key === "INTRUSION_WARN_2") {
          eventTitle = "무단침입 - 2차 경고 방송"
          noticeKind = "warn2"
          noticeType = 1
        } else if (data.tts_key === "EMERGENCY_GUIDE" || data.tts_key === "EVACUATION_GUIDE") {
          eventTitle = "위험감지 - 응급 안내 방송"
          noticeKind = "emergency"
          noticeType = 2
        } else if (situation === 1) {
          eventTitle = "무단침입"
        } else if (situation === 2) {
          eventTitle = "위험감지"
          noticeKind = "emergency"
          noticeType = 2
        }

        addLog(
          situation === 2 ? 2 : situation === 1 ? 1 : "n",
          eventTitle,
          data.stt_text?.trim()
            ? `음성 감지: "${data.stt_text.trim()}"`
            : data.reason || ""
        )

        if (data.stt_text && data.stt_text.trim()) {
          addLog(
            "voice",
            "음성 인식 결과",
            `"${data.stt_text.trim()}"`
          )
        }

        // 실제 백엔드가 경고/응급 TTS를 보낸 경우에만 알림 생성
        if (noticeKind) {
          setNotifications(prev => [{
            id: Date.now() + Math.random(),
            zoneId: selectedZoneIdRef.current,
            zoneName: activeZoneName,
            coord: activeZoneCoord,
            addr: activeZoneAddr,
            kind: noticeKind,
            type: noticeType,
            title: noticeKind === "emergency" ? "응급상황" : "무단침입",
            message:
              noticeKind === "warn1" ? "1차 경고 방송 송출" :
              noticeKind === "warn2" ? "2차 경고 방송 송출" :
              "응급 안내 방송 송출",
            time: data.timestamp || nowStr(),
            read: false,
          }, ...prev].slice(0, 30))
        }
        if (situation === 0) {
          setDetected(false)
          setElapsed(0)
          setPersonEl(0)
          setCurMsg(null)
          return
        }

        setDetected(true)

        let type = ""
        if (data.tts_key === "INTRUSION_WARN_1") type = "1차 경고 방송"
        else if (data.tts_key === "INTRUSION_WARN_2") type = "2차 경고 방송"
        else if (data.tts_key === "EMERGENCY_GUIDE" || data.tts_key === "EVACUATION_GUIDE") type = "응급 안내 방송"

        const msg = data.tts_message || ""
        if (msg && type) {
          setCurMsg({ text: msg, type })
          addLog(type === "응급 안내 방송" ? "emg" : "warn", `${type} 송출`, msg)
        } else {
          setCurMsg(null)
        }
      }

      ws.onerror = (err) => {
        console.error("WebSocket 에러:", err)
      }

      ws.onclose = () => {
        if (closed) return
        addLog("sys", "백엔드 연결 끊김", "3초 후 재연결")
        reconnectRef.current = setTimeout(connect, 3000)
      }
    }

    connect()

    return () => {
      closed = true
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      if (wsRef.current) wsRef.current.close()
    }
  }, [addLog, sendTtsConfig])


  const togglePause = () => {
    const next = !pausedRef.current
    setPaused(next)

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: "pause",
        paused: next,
      }))
      addLog("sys", next ? "감지 일시정지 요청" : "감지 재개 요청", `관리자 ${adminRef.current}`)
    } else {
      addLog("sys", "서버 미연결", "WebSocket 연결 후 다시 시도하세요")
    }
  }

  const unreadCount = notifications.filter(n => !n.read).length

  const switchToZone = (notice) => {
    const zone = zones.find(z => z.id === notice.zoneId || z.name === notice.zoneName)

    if (zone) {
      selectZone(zone)
    } else {
      onUpdateConfig({ ...configRef.current, zone: notice.zoneName || "관리구역 미지정" })
      setMapCoord(notice.coord || "37.5665° N, 126.9780° E")
      setMapAddr(notice.addr || notice.zoneName || "관할 구역 주소 미상")
    }

    setNotifications(prev =>
      prev.map(n => n.id === notice.id ? { ...n, read: true } : n)
    )
    setNotifPanelOpen(false)
  }

  const runSelfCheck = () => {
    setSelfCheckRunning(true)
    setSelfCheckResult(null)

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "self_check" }))
      addLog("sys", "자가진단 요청", "백엔드에 시스템 점검 요청")
    } else {
      setSelfCheckRunning(false)
      setSelfCheckResult([
        { label:"마이크 연결", ok:false },
        { label:"BEATs 모델", ok:false },
        { label:"TTS 엔진", ok:false },
        { label:"서버 연결", ok:false },
        { label:"로그 시스템", ok:false },
      ])
      addLog("sys", "자가진단 실패", "WebSocket 서버 미연결")
    }
  }

  const sd = STATUS_DATA[status]
  const parseCoord = (coord) => {
    const nums = String(coord).match(/-?\d+(\.\d+)?/g)
    return {
      lat: nums?.[0] || "37.5665",
      lon: nums?.[1] || "126.9780",
    }
  }

  const { lat, lon } = parseCoord(mapCoord)
  const selectedZone = zones.find(z => z.id === selectedZoneId)
  const currentZoneName = selectedZone?.name || config.zone || "관리구역 미지정"
  const mapSrc =
    `/map.html?lat=${encodeURIComponent(lat)}` +
    `&lon=${encodeURIComponent(lon)}` +
    `&name=${encodeURIComponent(currentZoneName)}` +
    `&addr=${encodeURIComponent(mapAddr || "관할 구역 주소 미상")}` +
    `&status=${status === 2 ? "danger" : status === 1 ? "warning" : "normal"}` +
    `&key=${encodeURIComponent(VWORLD_KEY || "")}`
  /* 레이아웃 스타일 */
  const hdrSt = { display:"flex", alignItems:"center", gap:8, padding:"9px 16px", borderBottom:`1px solid ${C.bd}`, background:"rgba(7,14,28,.96)", flexShrink:0, flexWrap:"wrap", rowGap:6 }
  const chipSt = { fontSize:10, color:C.t3, padding:"3px 8px", background:"rgba(255,255,255,.025)", border:`1px solid ${C.bd}`, borderRadius:4, display:"flex", alignItems:"center", gap:4, whiteSpace:"nowrap" }
  const mBtnSt = { background:"none", border:`1px solid ${C.bd}`, borderRadius:5, padding:"4px 9px", color:C.t2, cursor:"pointer", fontSize:10, fontFamily:"inherit", whiteSpace:"nowrap" }
  const cardSt = { background:C.card, border:`1px solid ${C.bd}`, borderRadius:8, overflow:"hidden" }
  const modalOverlay = { position:"absolute", top:0, left:0, right:0, bottom:0, background:"rgba(0,0,0,0.7)", display:"flex", alignItems:"center", justifyContent:"center", zIndex:100, backdropFilter:"blur(2px)" }

  return (
    <div style={{ display:"flex", flexDirection:"column", height:"100vh", overflow:"hidden", position:"relative" }}>

      {/* ── 헤더 ── */}
      <div style={hdrSt}>

        {/* 좌측: 프로그램명  현재 관리구역명  로그인 ID */}
        <div style={{ display:"flex", alignItems:"center", gap:8 }}>
          <div style={{ fontSize:14, fontWeight:800, whiteSpace:"nowrap" }}>🔊 SoundGuard</div>
          <div style={{ fontSize:10, color:C.t2, padding:"3px 10px", background:"rgba(255,255,255,.04)", border:`1px solid ${C.bd}`, borderRadius:20, maxWidth:200, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>
            {config.zone || "관리구역 미지정"}
          </div>
          <div style={chipSt}>👤 {adminId}</div>
        </div>

        {/* 우측: 감지 일시정지 | 안내멘트 설정 | 알림 | 설정 */}
        <div style={{ marginLeft:"auto", display:"flex", alignItems:"center", gap:5, flexWrap:"wrap" }}>

          {/* 감지 일시정지 */}
          <button onClick={togglePause} style={{ ...mBtnSt, color:paused?C.green:C.amber, borderColor:paused?"rgba(52,211,153,.3)":"rgba(251,191,36,.3)", background:paused?"rgba(52,211,153,.07)":"rgba(251,191,36,.07)" }}>
            {paused ? "▶ 감지 재개" : "⏸ 감지 일시정지"}
          </button>

          {/* 안내 멘트 설정 */}
          <button onClick={() => setMentPopup(true)} style={{ ...mBtnSt, color:C.t1, background:"rgba(255,255,255,.05)" }}>
            📝 안내멘트 설정
          </button>

          {/* 알림 버튼 */}
          <button
            onClick={() => setNotifPanelOpen(p => !p)}
            style={{ ...mBtnSt, position:"relative", color: unreadCount > 0 ? C.cyan : C.t2, borderColor: unreadCount > 0 ? "rgba(34,211,238,.3)" : C.bd, background: unreadCount > 0 ? "rgba(34,211,238,.07)" : "none" }}
          >
            🔔 알림
            {unreadCount > 0 && (
              <span style={{ marginLeft:5, background:C.red, color:"#fff", borderRadius:10, fontSize:9, fontWeight:800, padding:"1px 5px", lineHeight:"15px", display:"inline-block", verticalAlign:"middle" }}>
                {unreadCount}
              </span>
            )}
          </button>

          {/* 설정 */}
          <button style={{ ...mBtnSt }} onClick={() => setSettingsModal(true)}>⚙ 설정</button>
        </div>
      </div>

      {/* ── 바디 (좌/우 2단 레이아웃) ── */}
      <div style={{ display:"grid", gridTemplateColumns:"280px 1fr", flex:1, overflow:"hidden", minHeight:0 }}>

        {/* 좌측 패널 */}
        <div style={{ overflowY:"auto", padding:12, display:"flex", flexDirection:"column", gap:10, borderRight:`1px solid ${C.bd}` }}>

          {/* 상태 배너 */}
          <div style={{ borderRadius:10, border:`1px solid ${sd.bd}`, background:sd.bg, padding:"14px", display:"flex", flexDirection:"column", alignItems:"center", textAlign:"center", gap:8, transition:"background .4s,border-color .4s", flexShrink:0 }}>
            <div style={{ width:44, height:44, borderRadius:10, background:"rgba(255,255,255,.06)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:22, color:sd.c }}>{sd.ico}</div>
            <div>
              <div style={{ fontSize:9, textTransform:"uppercase", letterSpacing:".15em", fontWeight:700, color:sd.c, marginBottom:3 }}>{sd.tag}</div>
              <div style={{ fontSize:20, fontWeight:800, letterSpacing:"-.02em", color:sd.c }}>{sd.name}</div>
              <div style={{ fontSize:11, color:C.t2, marginTop:2 }}>{sd.desc}</div>
            </div>
            {status !== 0 && (
              <div style={{ marginTop:6 }}>
                <div style={{ fontSize:8, textTransform:"uppercase", letterSpacing:".1em", color:C.t3 }}>발생 후 경과</div>
                <div style={{ fontSize:22, fontWeight:800, fontFamily:"'Courier New',monospace", color:sd.c }}>{fmt(elapsed)}</div>
              </div>
            )}
          </div>

          {/* 구역 정보 */}
          <div style={{ ...cardSt, flexShrink:0 }}>
            <div style={mcHeadSt}><span style={mctSt}>📍 구역 정보</span></div>
            <div style={{ display:"flex", flexDirection:"column" }}>
              {[["구역명", currentZoneName||"—"], ["감지 장치", "마이크 #1"], ["모니터링 시작", startTime.current]].map(([l,v])=>(
                <div
                  key={l}
                  style={{ padding:"10px 12px", borderBottom:`1px solid ${C.bd}`, cursor: l==="구역명" ? "pointer" : "default", transition:"background-color 0.2s" }}
                  onMouseOver={e => { if(l==="구역명") { e.currentTarget.style.backgroundColor="rgba(34,211,238,.15)"; e.currentTarget.children[1].style.color=C.cyan } }}
                  onMouseOut={e => { if(l==="구역명") { e.currentTarget.style.backgroundColor="transparent"; e.currentTarget.children[1].style.color=C.t1 } }}
                  onClick={() => { if(l==="구역명") setZoneModal(true) }}
                >
                  <div style={{ fontSize:8, textTransform:"uppercase", letterSpacing:".12em", color:C.t3, marginBottom:4, fontWeight:700 }}>{l}</div>
                  <div style={{ fontSize:12, fontWeight:700, transition:"color 0.2s" }}>{v}</div>
                </div>
              ))}
            </div>
          </div>

          {/* 감지된 인물 */}
          <div style={{ ...cardSt, flexShrink:0 }}>
            <div style={mcHeadSt}>
              <span style={mctSt}>👤 감지된 인물</span>
              <span style={{ fontSize:8, padding:"2px 6px", border:`1px solid ${detected?"rgba(251,191,36,.28)":C.bd}`, borderRadius:3, fontWeight:700, background:detected?"rgba(251,191,36,.1)":"rgba(255,255,255,.04)", color:detected?C.amber:C.t3 }}>{detected?"감지 중":"미감지"}</span>
            </div>
            <div style={{ padding:"10px 12px" }}>
              <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:10 }}>
                <div style={{ position:"relative", width:9, height:9, borderRadius:"50%", background:detected?C.amber:C.t3, flexShrink:0 }} />
                <div>
                  <div style={{ fontSize:12, fontWeight:700 }}>{detected?"인원 감지됨":"감지 없음"}</div>
                  <div style={{ fontSize:10, color:C.t2, marginTop:1 }}>{detected?"구역 내 비허가 인원 존재":"현재 구역 내 인원 없음"}</div>
                </div>
              </div>
              <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
                {[["구역 내 체류", fmt(personEl)], ["마지막 감지음", lastSnd]].map(([l,v])=>(
                  <div key={l} style={{ background:"rgba(255,255,255,.03)", borderRadius:5, padding:"7px 9px", display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                    <div style={{ fontSize:8, textTransform:"uppercase", letterSpacing:".1em", color:C.t3, fontWeight:700 }}>{l}</div>
                    <div style={{ fontSize:11, fontWeight:700, fontFamily:"'Courier New',monospace" }}>{v}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* 이벤트 로그 */}
          <div style={{ ...cardSt, flex:1, display:"flex", flexDirection:"column", minHeight:400 }}>
            <div style={mcHeadSt}>
              <span style={mctSt}>이벤트 로그</span>
              <button style={{...tbtnSt, padding:"2px 6px", fontSize:9}} onClick={()=>setLogs([])}>초기화</button>
            </div>
            <div style={{ flex:1, overflowY:"auto", padding:8 }}>
              {logs.map(log => {
                const lc = LOG_COLORS[log.type] || LOG_COLORS.sys
                return (
                  <div key={log.id} style={{ padding:"7px 9px", borderRadius:4, borderLeft:`2px solid ${lc.c}`, marginBottom:5, background:"rgba(255,255,255,.02)" }}>
                    <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:2 }}>
                      <span style={{ fontSize:8, fontWeight:800, letterSpacing:".07em", textTransform:"uppercase", color:lc.c }}>{lc.label}</span>
                      <span style={{ fontSize:8, fontFamily:"'Courier New',monospace", color:C.t3 }}>{log.t}</span>
                    </div>
                    <div style={{ fontSize:11, color:C.t1 }}>{log.title}</div>
                    {log.detail && <div style={{ fontSize:9, color:C.t3, marginTop:2, fontFamily:"'Courier New',monospace", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{log.detail}</div>}
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {/* 중앙 패널 */}
        <div style={{ display:"flex", flexDirection:"column", padding:12, gap:10, overflow:"hidden" }}>

          
          {/* 지도 시각화 */}
          <div style={{ ...cardSt, flex:1, position:"relative", background:"#0a1424" }}>
            <div style={{
              position:"absolute",
              top:12,
              left:12,
              background:"rgba(10,20,40,.8)",
              padding:"5px 10px",
              borderRadius:6,
              border:`1px solid ${C.bd}`,
              fontSize:11,
              fontWeight:700,
              color:C.t1,
              zIndex:2
            }}>
              🗺 현재 음성감지구역 지도
            </div>

            <iframe
              key={mapSrc}
              title="SoundGuard Map"
              src={mapSrc}
              style={{
                width:"100%",
                height:"100%",
                border:"none",
                display:"block",
                borderRadius:8,
              }}
            />

            <div
              style={{
                position:"absolute",
                bottom:12,
                left:12,
                background:"rgba(10,20,40,.9)",
                padding:"6px 10px",
                borderRadius:6,
                border:`1px solid ${C.bd}`,
                fontSize:10,
                color:C.t2,
                cursor:"pointer",
                transition:"border-color 0.2s",
                zIndex:2
              }}
              onMouseOver={e => e.currentTarget.style.borderColor = C.cyan}
              onMouseOut={e => e.currentTarget.style.borderColor = C.bd}
              onClick={() => setMapInfoModal(true)}
            >
              <span style={{color:C.t1, fontWeight:700, marginRight:6}}>좌표</span> {mapCoord}<br/>
              <span style={{color:C.t1, fontWeight:700, marginRight:6}}>주소</span> {mapAddr}
            </div>
          </div>

          {/* BEATs */}
          <div style={{ ...cardSt, flexShrink:0 }}>
            <div style={mcHeadSt}>
              <span style={mctSt}>⚡ 실시간 음향 분석</span>
            </div>
            <div style={{ display:"flex", gap:10, padding:"10px 12px" }}>
              {[["배경음", beats.background, C.green], ["큰소음", beats.loud_noise, C.t2], ["침입음", beats.intrusion, C.amber], ["응급음", beats.emergency, C.red], ["충격음", beats.impact_noise, C.violet]].map(([lbl, val, color]) =>(
                <div key={lbl} style={{ flex:1, background:"rgba(255,255,255,.03)", borderRadius:6, padding:"8px" }}>
                  <div style={{ fontSize:10, color:C.t2, marginBottom:5 }}>{lbl}</div>
                  <div style={{ display:"flex", alignItems:"center", gap:6 }}>
                    <div style={{ flex:1, height:4, background:"#05101e", borderRadius:2, overflow:"hidden" }}>
                      <div style={{ height:"100%", borderRadius:2, background:color, width:`${val}%`, transition:"width .7s ease" }} />
                    </div>
                    <div style={{ fontSize:11, fontWeight:700, fontFamily:"'Courier New',monospace", color, width:24, textAlign:"right" }}>{val}%</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 현재 메시지 */}
          <div style={{ ...cardSt, flexShrink:0 }}>
            <div style={mcHeadSt}><span style={mctSt}>📢 현재 송출 중인 메시지</span></div>
            <div style={{ padding:"12px" }}>
              <div style={{ fontSize:12, color:curMsg?C.t1:C.t3, lineHeight:1.6, padding:"10px", background:"rgba(255,255,255,.03)", borderRadius:6, borderLeft:`2px solid ${curMsg?C.cyan:C.bd}`, fontStyle:curMsg?"normal":"italic" }}>
                {curMsg ? (
                  <>
                    <span style={{display:"inline-block", padding:"1px 6px", background:C.cyan, color:"#000", borderRadius:3, fontSize:9, fontWeight:800, marginRight:8, verticalAlign:"middle"}}>{curMsg.type}</span>
                    {curMsg.text}
                  </>
                ) : "현재 송출 중인 메시지 없음"}
              </div>
            </div>
          </div>
        </div>

      </div>

      {/* ── 푸터 ── */}
      <div style={{ borderTop:`1px solid ${C.bd}`, padding:"8px 14px", display:"flex", alignItems:"center", gap:7, flexShrink:0, background:"rgba(7,14,28,.8)" }}>
        <div style={{ display:"flex", alignItems:"center", gap:7, fontSize:10 }}>
          <span style={{ display:"inline-block", width:5, height:5, borderRadius:"50%", background:paused?C.amber:C.green }} />
          <span style={{ color:C.t3 }}>{paused ? "감지 일시정지" : "시스템 활성"}</span>
          <span style={{ color:C.t3 }}>|</span>
          <span style={{ fontFamily:"'Courier New',monospace", fontSize:11, color:C.t2 }}>{clock}</span>
        </div>
      </div>

      {/* ── 모달 팝업 영역 ── */}
      {mentPopup && (
        <div style={modalOverlay}>
          <div style={{ background:C.card, padding:24, borderRadius:12, border:`1px solid ${C.bd2}`, width:300, textAlign:"center" }}>
            <div style={{ fontSize:16, fontWeight:800, marginBottom:20 }}>안내 멘트 설정 메뉴</div>
            <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
              <button style={{...btnCyanSt, background:C.bd, color:C.t1}} onClick={() => { setMentPopup(false); onGoConfig(); }}>초기 설정 (시스템 초기화)</button>
              <button style={btnCyanSt} onClick={() => { setMentPopup(false); setMentEditModal(true); }}>멘트 수정 (현재 상태 유지)</button>
              <button style={{...tbtnSt, marginTop:10}} onClick={() => setMentPopup(false)}>닫기</button>
            </div>
          </div>
        </div>
      )}

      {mentEditModal && (
        <div style={modalOverlay}>
          <MentEditOverlay config={config} onUpdateConfig={onUpdateConfig} onClose={() => setMentEditModal(false)} wsRef={wsRef} />
        </div>
      )}

      {zoneModal && (
        <div style={modalOverlay}>
          <div style={{ background:C.card, padding:24, borderRadius:12, border:`1px solid ${C.bd2}`, width:420 }}>
            <div style={{ fontSize:16, fontWeight:800, marginBottom:16 }}>
              구역 선택 및 관리
            </div>

            <div style={{ maxHeight:220, overflowY:"auto", marginBottom:16, border:`1px solid ${C.bd}`, borderRadius:6, padding:8 }}>
              {zones.map(zone => (
                <div
                  key={zone.id}
                  style={{
                    display:"flex",
                    justifyContent:"space-between",
                    alignItems:"center",
                    padding:"8px",
                    background: zone.id === selectedZoneId ? "rgba(34,211,238,.16)" : "rgba(255,255,255,.03)",
                    marginBottom:4,
                    borderRadius:4,
                    border: zone.id === selectedZoneId ? `1px solid ${C.cyan}` : "1px solid transparent",
                  }}
                >
                  <div
                    style={{ cursor:"pointer", flex:1 }}
                    onClick={() => {
                      selectZone(zone)
                      setZoneModal(false)
                    }}
                  >
                    <div style={{ fontSize:12, fontWeight:800, color:C.t1 }}>{zone.name}</div>
                    <div style={{ fontSize:9, color:C.t3, marginTop:2 }}>{zone.coord}</div>
                    <div style={{ fontSize:9, color:C.t2, marginTop:1 }}>{zone.addr}</div>
                  </div>

                  <button
                    style={{ background:"none", border:"none", color:C.red, cursor:"pointer", fontSize:10 }}
                    onClick={() => deleteZone(zone.id)}
                  >
                    삭제
                  </button>
                </div>
              ))}
            </div>

            <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
              <input
                style={inputSt}
                value={newZoneName}
                onChange={e => setNewZoneName(e.target.value)}
                placeholder="새 구역명"
              />

              <input
                style={inputSt}
                value={newZoneCoord}
                onChange={e => setNewZoneCoord(e.target.value)}
                placeholder="좌표 예: 37.5665° N, 126.9780° E"
              />

              <input
                style={inputSt}
                value={newZoneAddr}
                onChange={e => setNewZoneAddr(e.target.value)}
                placeholder="주소 또는 설명"
              />

              <button
                style={{...btnCyanSt, width:"100%"}}
                onClick={addZone}
              >
                추가
              </button>
            </div>

            <div style={{ textAlign:"right", marginTop:16 }}>
              <button
                style={{...btnCyanSt, width:"auto", background:C.bd, color:C.t1}}
                onClick={() => setZoneModal(false)}
              >
                닫기
              </button>
            </div>
          </div>
        </div>
      )}

      {mapInfoModal && (
        <div style={modalOverlay}>
          <div style={{ background:C.card, padding:24, borderRadius:12, border:`1px solid ${C.bd2}`, width:320 }}>
            <div style={{ fontSize:16, fontWeight:800, marginBottom:16 }}>지도 위치 설정</div>
            <div style={{ marginBottom:12 }}>
              <label style={labelSt}>GPS 좌표</label>
              <input style={inputSt} value={mapCoord} onChange={e=>setMapCoord(e.target.value)} />
            </div>
            <div style={{ marginBottom:20 }}>
              <label style={labelSt}>주소</label>
              <input style={inputSt} value={mapAddr} onChange={e=>setMapAddr(e.target.value)} />
            </div>
            <div style={{ display:"flex", gap:10 }}>
              <button
                style={{...btnCyanSt, background:C.bd, color:C.t1}}
                onClick={() => {
                  if (selectedZoneId) {
                    setZones(prev =>
                      prev.map(z =>
                        z.id === selectedZoneId
                          ? { ...z, coord: mapCoord, addr: mapAddr }
                          : z
                      )
                    )
                  }
                  setZoneModal(false)
                  setMapInfoModal(false)
                }}
              >
                확인
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 알림 패널 (fixed 드롭다운) ── */}
      {notifPanelOpen && (
        <>
          {/* 바깥 클릭 닫기용 투명 레이어 */}
          <div style={{ position:"fixed", inset:0, zIndex:149 }} onClick={() => setNotifPanelOpen(false)} />
          <div style={{
            position:"fixed", top:48, right:10,
            width:310, maxHeight:400,
            background:C.card, border:`1px solid ${C.bd2}`,
            borderRadius:10, zIndex:150,
            display:"flex", flexDirection:"column",
            boxShadow:"0 10px 40px rgba(0,0,0,.6)",
            overflow:"hidden",
          }}>
            {/* 패널 헤더 */}
            <div style={{ padding:"9px 14px", borderBottom:`1px solid ${C.bd}`, display:"flex", justifyContent:"space-between", alignItems:"center", flexShrink:0 }}>
              <span style={{ fontSize:12, fontWeight:800, color:C.t1 }}>🔔 다른 구역 알림</span>
              <div style={{ display:"flex", gap:4 }}>
                {unreadCount > 0 && (
                  <button style={{...tbtnSt, fontSize:10}} onClick={() => setNotifications(prev => prev.map(n => ({...n, read:true})))}>
                    모두 읽음
                  </button>
                )}
                <button style={{...tbtnSt, fontSize:11}} onClick={() => setNotifPanelOpen(false)}>✕</button>
              </div>
            </div>

            {/* 알림 목록 */}
            <div style={{ overflowY:"auto", flex:1 }}>
              {notifications.length === 0 ? (
                <div style={{ padding:"28px 16px", textAlign:"center", color:C.t3, fontSize:11 }}>
                  다른 관리구역의 알림이 없습니다
                </div>
              ) : (
                notifications.map(n => (
                  <div
                    key={n.id}
                    style={{
                      padding:"10px 14px",
                      borderBottom:`1px solid ${C.bd}`,
                      cursor:"pointer",
                      background: n.read ? "transparent" : "rgba(34,211,238,.04)",
                      transition:"background .15s",
                    }}
                    onClick={() => switchToZone(n)}
                    onMouseOver={e => e.currentTarget.style.background="rgba(255,255,255,.05)"}
                    onMouseOut={e => e.currentTarget.style.background = n.read ? "transparent" : "rgba(34,211,238,.04)"}
                  >
                    <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:4 }}>
                      <div style={{ display:"flex", alignItems:"center", gap:6 }}>
                        <span style={{ fontSize:9, fontWeight:800, color: n.type===2 ? C.red : C.amber }}>
                          {n.kind === "emergency" ? "⚠ 응급상황" : n.kind === "warn2" ? "! 2차 경고" : "! 1차 경고"}
                        </span>
                        <span style={{ fontSize:9, color:C.t3 }}>·</span>
                        <span style={{ fontSize:9, color:C.t2, fontWeight:700 }}>{n.zoneName}</span>
                      </div>
                      {!n.read && <span style={{ width:6, height:6, borderRadius:"50%", background:C.cyan, display:"inline-block", flexShrink:0 }} />}
                    </div>
                    <div style={{ fontSize:11, color:C.t1, marginBottom:3 }}>{n.message}</div>
                    <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                      <span style={{ fontSize:9, color:C.t3, fontFamily:"'Courier New',monospace" }}>{n.time}</span>
                      <span style={{ fontSize:9, color:C.cyan }}>구역 전환 →</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}

      {/* ── 설정 팝업 모달 ── */}
      {settingsModal && (
        <div style={modalOverlay} onClick={e => e.target === e.currentTarget && setSettingsModal(false)}>
          <div style={{ background:C.card, borderRadius:12, border:`1px solid ${C.bd2}`, width:360, overflow:"hidden" }}>

            {/* 모달 헤더 */}
            <div style={{ padding:"13px 18px", borderBottom:`1px solid ${C.bd}`, background:C.sf, display:"flex", justifyContent:"space-between", alignItems:"center" }}>
              <span style={{ fontSize:14, fontWeight:800 }}>⚙ 시스템 설정</span>
              <button style={tbtnSt} onClick={() => setSettingsModal(false)}>✕</button>
            </div>

            <div style={{ padding:"18px" }}>

              {/* 현재 접속 IP */}
              <div style={{ marginBottom:16, padding:"12px 14px", background:"rgba(255,255,255,.025)", borderRadius:8, border:`1px solid ${C.bd}` }}>
                <div style={{ fontSize:9, textTransform:"uppercase", letterSpacing:".12em", color:C.t3, fontWeight:700, marginBottom:6 }}>현재 접속 IP</div>
                <div style={{ fontSize:13, fontWeight:700, fontFamily:"'Courier New',monospace", color:C.cyan, display:"flex", alignItems:"center", gap:8 }}>
                  <span style={{ display:"inline-block", width:7, height:7, borderRadius:"50%", background:C.green, flexShrink:0 }} />
                  {serverIP}
                </div>
              </div>

              {/* 자가진단 */}
              <div style={{ marginBottom:16 }}>
                <div style={{ fontSize:9, textTransform:"uppercase", letterSpacing:".12em", color:C.t3, fontWeight:700, marginBottom:8 }}>자가진단</div>
                <button
                  style={{ ...btnCyanSt, opacity:selfCheckRunning ? 0.65 : 1 }}
                  onClick={runSelfCheck}
                  disabled={selfCheckRunning}
                >
                  {selfCheckRunning ? "🔍 진단 중..." : "🔍 자가진단 실행"}
                </button>

                {selfCheckResult && (
                  <div style={{ marginTop:10, background:"rgba(255,255,255,.02)", borderRadius:6, border:`1px solid ${C.bd}`, overflow:"hidden" }}>
                    {selfCheckResult.map(item => (
                      <div key={item.label} style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"7px 12px", borderBottom:`1px solid ${C.bd}` }}>
                        <span style={{ fontSize:11, color:C.t2 }}>{item.label}</span>
                        <span style={{ fontSize:11, fontWeight:800, color: item.ok ? C.green : C.red }}>
                          {item.ok ? "✓ 정상" : "✗ 오류"}
                        </span>
                      </div>
                    ))}
                    <div style={{ padding:"7px 12px", fontSize:10, color:C.green, fontWeight:700 }}>모든 항목 정상</div>
                  </div>
                )}
              </div>

              {/* 로그아웃 */}
              <div style={{ borderTop:`1px solid ${C.bd}`, paddingTop:14 }}>
                <button
                  style={{ ...btnCyanSt, background:"rgba(248,113,113,.08)", color:C.red, border:`1px solid rgba(248,113,113,.25)` }}
                  onClick={() => { setSettingsModal(false); onLogout() }}
                >
                  로그아웃
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* CSS 애니메이션 */}
      <style>{`
        @keyframes ping {
          75%, 100% { transform: scale(2); opacity: 0; }
        }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,.15); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,.3); }
        * { scrollbar-width: thin; scrollbar-color: rgba(255,255,255,.15) transparent; }
      `}</style>
    </div>
  )
}

/* ── 파형 아이콘 (순수 CSS) ─────────────────────────────── */
const waveKf = `@keyframes wv { 0%,100%{opacity:.3;transform:scaleY(.6)} 50%{opacity:1;transform:scaleY(1)} }`
if (typeof document !== "undefined") {
  const s = document.createElement("style"); s.textContent = waveKf; document.head.appendChild(s)
}
function WaveIcon() {
  const barBase = { width:2.5, borderRadius:2, background:C.cyan, display:"inline-block", animationName:"wv", animationDuration:".8s", animationIterationCount:"infinite", transformOrigin:"bottom" }
  return (
    <div style={{ display:"flex", alignItems:"flex-end", gap:2, height:14 }}>
      {[[5,0],[10,.15],[14,.3],[8,.45]].map(([h, delay], i) => (
        <div key={i} style={{ ...barBase, height:h, animationDelay:`${delay}s` }} />
      ))}
    </div>
  )
}
