import { useState, useEffect, useRef, useCallback } from "react"
import { Volume2, User, Megaphone, Play, Pause, FileText, Bell, Settings, MapPin, Map, Activity, ShieldCheck, AlertTriangle, ShieldAlert, Check, X, Search } from "lucide-react"
import "./styles/dashboard.css"
const VWORLD_KEY = import.meta.env.VITE_VWORLD_KEY
console.log("VWORLD_KEY:", VWORLD_KEY)
/* ─── 상수 ──────────────────────────────────────────────── */
const C = {
  bg:"var(--sg-bg)", sf:"var(--sg-surface)", card:"var(--sg-card)", bd:"var(--sg-border)", bd2:"var(--sg-border-strong)",
  t1:"var(--sg-text)", t2:"var(--sg-text-muted)", t3:"var(--sg-text-dim)",
  green:"var(--sg-green)", amber:"var(--sg-amber)", red:"var(--sg-red)", cyan:"var(--sg-cyan)", violet:"var(--sg-violet)",
  greenSoft:"var(--sg-green-soft)", greenBorder:"var(--sg-green-border)",
  amberSoft:"var(--sg-amber-soft)", amberBorder:"var(--sg-amber-border)",
  redSoft:"var(--sg-red-soft)", redBorder:"var(--sg-red-border)",
  cyanSoft:"var(--sg-cyan-soft)", cyanBorder:"var(--sg-cyan-border)",
  violetSoft:"var(--sg-violet-soft)", violetBorder:"var(--sg-violet-border)",
  panel:"var(--sg-panel-soft)", panel2:"var(--sg-panel-muted)", panel3:"var(--sg-panel-strong)", overlay:"var(--sg-panel-overlay)",
  mapBg:"var(--sg-map-bg)", videoBg:"var(--sg-video-bg)", primaryText:"var(--sg-primary-text)",
  rXs:"var(--sg-radius-xs)", rSm:"var(--sg-radius-sm)", rMd:"var(--sg-radius-md)", rLg:"var(--sg-radius-lg)", rXl:"var(--sg-radius-xl)", rPill:"var(--sg-radius-pill)",
  mono:"var(--sg-font-mono)", sans:"var(--sg-font-sans)", shadowLg:"var(--sg-shadow-lg)",
}

const STATUS_DATA = {
  0:{ c:C.green, bg:C.greenSoft, bd:C.greenBorder, Ico:ShieldCheck,    tag:"현재 상태 · 정상",  name:"정상",    desc:"구역이 정상적으로 관리 중입니다" },
  1:{ c:C.amber, bg:C.amberSoft, bd:C.amberBorder, Ico:AlertTriangle,  tag:"현재 상태 · 경고",  name:"무단침입", desc:"비허가 인원 진입 감지 — 경고 방송 송출 중" },
  2:{ c:C.red,   bg:C.redSoft,   bd:C.redBorder,   Ico:ShieldAlert,    tag:"현재 상태 · 긴급", name:"위험 감지", desc:"위험 상황 감지 — 즉각 대응 필요" },
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

const SOUND_LABEL_TEXT = {
  background: "배경음",
  speech: "사람 목소리",
  footsteps: "발소리",
  interaction: "문소리",
  impact_noise: "충격음",
  emergency: "응급음",
  low_volume: "작은 소리",
  empty: "무음",
}

const looksLikeDeviceName = (name="") => {
  const text = String(name || "").trim().toLowerCase()
  const numbered = (prefix) => {
    if (text === prefix) return true
    if (!text.startsWith(prefix)) return false
    return /^\d+$/.test(text.slice(prefix.length).trim().replace(/^[-_() ]+|[-_() ]+$/g, ""))
  }
  return text.startsWith("핸드폰 센서") || numbered("센서") || numbered("기계") || numbered("machine") || numbered("device")
}

const DEFAULT_MSGS = {
  w1: "무단 침입이 감지되었습니다. 즉시 퇴거하지 않을 시 관계기관에 신고 조치됩니다.",
  w2: "귀하의 위치 정보가 관계기관에 전송되었습니다. 즉시 이 구역을 이탈하십시오.",
  emg:"위험 상황이 감지되었습니다. 신속히 대피하시고 119에 신고하여 주십시오.",
}

const genId = () => Math.random().toString(36).slice(2) + Date.now().toString(36)
const fmt = s => `${String(Math.floor(s/60)).padStart(2,"0")}:${String(s%60).padStart(2,"0")}`
const fmtUptime = s => { const h=Math.floor(s/3600); const m=Math.floor((s%3600)/60); const sec=s%60; return `${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}:${String(sec).padStart(2,"0")}` }
const nowStr = () => { const d=new Date(); return [d.getHours(),d.getMinutes(),d.getSeconds()].map(v=>String(v).padStart(2,"0")).join(":") }
const fs = size => `var(--sg-fs-${size})`
const normalizeServerBase = (value, fallbackProtocol="http") => {
  const raw = String(value || "localhost:8000").trim().replace(/\/+$/g, "")
  if (/^https?:\/\//i.test(raw)) return raw
  return `${fallbackProtocol}://${raw}`
}
const dashboardWsUrl = (value) => {
  const raw = String(value || "localhost:8000").trim().replace(/\/+$/g, "")
  if (/^wss?:\/\//i.test(raw)) return `${raw}/ws`
  if (/^https?:\/\//i.test(raw)) {
    const url = new URL(raw)
    return `${url.protocol === "https:" ? "wss" : "ws"}://${url.host}/ws`
  }
  const protocol = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss" : "ws"
  return `${protocol}://${raw}/ws`
}
const normalizeZoneFromServer = (zone={}) => ({
  ...zone,
  id: zone.id || zone.zone_id || genId(),
  name: zone.name || zone.zone_name || "관리구역 미지정",
  coord: zone.coord || "",
  label: zone.label || zone.addr || zone.address || "",
  addr: zone.addr || zone.address || zone.label || "",
})
const THEME_STORAGE_KEY = "soundguard-theme"
const getInitialTheme = () => {
  if (typeof window === "undefined") return "dark"
  return window.localStorage.getItem(THEME_STORAGE_KEY) || "dark"
}

/* ─── 공통 스타일은 styles/dashboard_2.css에서 관리 ──────────── */
/* ════════════════════════════════════════════════════════════
   메인 컴포넌트
════════════════════════════════════════════════════════════ */

export default function SoundGuardDashboard() {
  const [screen, setScreen] = useState("login")  // "login" | "config" | "main"
  const [adminId, setAdminId] = useState("")
  const [config, setConfig] = useState({ zone:"", w1:"", w2:"", emg:"" })
  const [theme, setTheme] = useState(getInitialTheme)
  const toggleTheme = useCallback(() => setTheme(prev => prev === "light" ? "dark" : "light"), [])
  useEffect(() => {
    document.body.classList.toggle("sg-theme-light", theme === "light")
    document.body.classList.toggle("sg-theme-dark", theme !== "light")
    window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  }, [theme])
  // ─── 백엔드 연결 설정 ──────────────────────────────────────────
  // [Vite 로컬 개발] server.py를 본인 PC에서 실행 후 아래 줄 사용
  // const SERVER_IP = "localhost:8000"
  //
  // [오라클 배포] .env.production 의 VITE_BACKEND_IP 자동 적용
  // frontend/.env.production → VITE_BACKEND_IP=공인IP:8000
  const SERVER_IP = import.meta.env.VITE_BACKEND_IP || "localhost:8000"
  // ──────────────────────────────────────────────────────────────

  const go = useCallback((scr, cfg) => {
    if (cfg) setConfig(cfg)
    setScreen(scr)
  }, [])

  return (
    <div style={{ minHeight:"100vh", background:C.bg, color:C.t1, fontFamily:C.sans, fontSize:fs(13) }}>
      {screen === "login"  && <LoginScreen  onLogin={id => { setAdminId(id); setScreen("main") }} />}
      {screen === "config" && <ConfigScreen adminId={adminId} initConfig={config} onSave={cfg => go("main", cfg)} onBack={() => setScreen("main")} />}
      {screen === "main"   && <MainScreen   adminId={adminId} config={config} serverIP={SERVER_IP} onGoConfig={() => setScreen("config")} onLogout={() => { setAdminId(""); setScreen("login") }} onUpdateConfig={(cfg)=>setConfig(cfg)} theme={theme} onToggleTheme={toggleTheme} />}
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
          <img src="/SoundGuardLogo_0.png" alt="SoundGuard" style={{ width:90, height:90, objectFit:"contain", margin:"0 auto 16px", display:"block" }} />
          <div style={{ fontSize:fs(9), letterSpacing:".2em", textTransform:"uppercase", color:C.t3, marginBottom:7 }}>Sound Guard System</div>
          <div style={{ fontSize:fs(20), fontWeight:800, letterSpacing:"-.02em" }}>음향 기반 위험 예방·구조 시스템</div>
          <div style={{ fontSize:fs(11), color:C.t2, marginTop:5 }}>상황실 관리자 전용</div>
        </div>

        {/* 카드 */}
        <div style={{ background:C.card, border:`1px solid ${C.bd2}`, borderRadius:C.rXl, padding:26 }}>
          <div style={{ fontSize:fs(14), fontWeight:800, marginBottom:20 }}>관리자 로그인</div>

          <div style={{ marginBottom:14 }}>
            <label className="sg-label">관리자 ID</label>
            <input className="sg-input" type="text" placeholder="admin" value={id} onChange={e=>setId(e.target.value)} onKeyDown={e=>e.key==="Enter"&&handle()} />
          </div>

          <div style={{ marginBottom:20, position:"relative" }}>
            <label className="sg-label">비밀번호</label>
            <input className="sg-input sg-input--password" type={showPw?"text":"password"} placeholder="••••••••" value={pw} onChange={e=>setPw(e.target.value)} onKeyDown={e=>e.key==="Enter"&&handle()} />
            <button onClick={()=>setShowPw(!showPw)} style={{ position:"absolute", right:10, bottom:10, background:"none", border:"none", color:C.t3, cursor:"pointer", fontSize:fs(11), padding:4 }}>{showPw?"숨김":"표시"}</button>
          </div>

          {error && <div style={{ background:C.redSoft, border:`1px solid ${C.redBorder}`, borderRadius:C.rMd, padding:"7px 11px", fontSize:fs(11), color:C.red, marginBottom:12 }}>{error}</div>}

          <button className="sg-button-primary" style={{ opacity:loading?0.6:1 }} onClick={handle} disabled={loading}>
            {loading ? "인증 중..." : "로그인"}
          </button>

          <div style={{ marginTop:13, padding:8, background:C.panel, borderRadius:C.rSm, fontSize:fs(10), color:C.t3, textAlign:"center" }}>
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

  const secSt = { background:C.card, border:`1px solid ${C.bd2}`, borderRadius:C.rXl, padding:18, marginBottom:14 }
  const hdSt  = { fontSize:fs(10), fontWeight:800, textTransform:"uppercase", letterSpacing:".1em", color:C.t3, marginBottom:12, display:"flex", alignItems:"center", gap:7 }
  const numSt = (bg=C.cyan) => ({ width:18, height:18, borderRadius:C.rPill, display:"flex", alignItems:"center", justifyContent:"center", fontSize:fs(9), fontWeight:800, background:bg, color:C.primaryText, flexShrink:0 })
  const exSt  = { background:C.panel, border:`1px solid ${C.bd}`, borderRadius:C.rMd, padding:"8px 11px", fontSize:fs(11), color:C.t2, marginBottom:9, lineHeight:1.6 }
  const pvSt  = { background:C.cyanSoft, border:`1px solid ${C.cyanBorder}`, borderRadius:C.rMd, padding:"8px 11px", fontSize:fs(11), color:C.cyan, marginTop:8, lineHeight:1.7 }
  const tagSt = { fontSize:fs(8), color:C.t3, background:C.panel2, padding:"2px 7px", borderRadius:C.rXs, fontWeight:400, textTransform:"none", letterSpacing:".04em" }
  return (
    <div style={{ display:"flex", flexDirection:"column", minHeight:"100vh" }}>
      {/* 헤더 */}
      <div style={{ display:"flex", alignItems:"center", gap:10, padding:"10px 22px", borderBottom:`1px solid ${C.bd}`, background:C.sf, position:"sticky", top:0, zIndex:20 }}>
        <div style={{ fontSize:fs(14), fontWeight:800 }}><span style={{display:"inline-flex",alignItems:"center",gap:6}}><img src="/SoundGuardLogo.png" alt="SoundGuard" style={{ width:34, height:34, objectFit:"contain" }} />SoundGuard</span></div>
        <div style={{ fontSize:fs(10), color:C.t3, padding:"2px 8px", background:C.panel2, borderRadius:C.rSm }}>안내 멘트 설정</div>
        <div style={{ marginLeft:"auto", display:"flex", alignItems:"center", gap:8 }}>
          <span style={{ fontSize:fs(10), color:C.t2, padding:"2px 8px", border:`1px solid ${C.bd}`, borderRadius:C.rPill }}>{adminId}</span>
          <button className="sg-text-button" onClick={onBack}>← 메인으로</button>
        </div>
      </div>

      {/* 바디 */}
      <div style={{ maxWidth:660, margin:"0 auto", padding:"28px 22px" }}>
        <h1 style={{ fontSize:fs(20), fontWeight:800, letterSpacing:"-.02em", marginBottom:5 }}>안내 멘트 설정</h1>
        <p style={{ fontSize:fs(12), color:C.t2, marginBottom:24, lineHeight:1.7 }}>상황별로 현장에 송출될 음성 메시지를 설정하세요. 1·2차 경고 멘트는 구역명이 자동으로 앞에 붙습니다.</p>

        {/* 구역명 */}
        <div style={secSt}>
          <div style={hdSt}><span style={numSt()}>1</span> 관리 구역명</div>
          <div style={exSt}><div style={{ fontSize:fs(8), textTransform:"uppercase", letterSpacing:".1em", color:C.t3, marginBottom:3, fontWeight:700 }}>입력 예시</div>강변 저수지 위험구역 &nbsp;/&nbsp; 폐공사장 A구역 &nbsp;/&nbsp; 사유지 출입금지 구역</div>
          <div style={{ marginBottom:9 }}><label className="sg-label">구역명</label><input className="sg-input" type="text" placeholder="예: 강변 저수지 위험구역" value={zone} onChange={e=>setZone(e.target.value)} /></div>
          <div style={pvSt}><div style={{ fontSize:fs(8), textTransform:"uppercase", letterSpacing:".1em", color:C.cyan, marginBottom:3, fontWeight:700 }}>첫 멘트 자동 생성</div>이곳은 <u>{z}</u> 입니다.</div>
        </div>

        {/* 1차 경고 */}
        <div style={secSt}>
          <div style={hdSt}><span style={numSt(C.amber)}>2</span> 1차 경고 멘트 <span style={tagSt}>5초 이상 체류 감지 시</span></div>
          <div style={exSt}><div style={{ fontSize:fs(8), textTransform:"uppercase", letterSpacing:".1em", color:C.t3, marginBottom:3, fontWeight:700 }}>작성 예시</div>{DEFAULT_MSGS.w1}</div>
          <div style={{ marginBottom:9 }}>
            <label className="sg-label">앞에 자동 삽입: <span style={{color:C.cyan}}>"{pfx}"</span></label>
            <textarea className="sg-input sg-input--textarea" placeholder="이후 경고 문구를 입력하세요..." rows={3} value={w1} onChange={e=>setW1(e.target.value)} />
          </div>
          <div style={pvSt}><div style={{ fontSize:fs(8), textTransform:"uppercase", letterSpacing:".1em", color:C.cyan, marginBottom:3, fontWeight:700 }}>전체 송출 메시지 미리보기</div>{pv1}</div>
        </div>

        {/* 2차 경고 */}
        <div style={secSt}>
          <div style={hdSt}><span style={numSt(C.red)}>3</span> 2차 경고 멘트 <span style={tagSt}>15초 이상 체류 감지 시</span></div>
          <div style={exSt}><div style={{ fontSize:fs(8), textTransform:"uppercase", letterSpacing:".1em", color:C.t3, marginBottom:3, fontWeight:700 }}>작성 예시</div>{DEFAULT_MSGS.w2}</div>
          <div style={{ marginBottom:9 }}>
            <label className="sg-label">앞에 자동 삽입: <span style={{color:C.cyan}}>"{pfx}"</span></label>
            <textarea className="sg-input sg-input--textarea" placeholder="이후 경고 문구를 입력하세요..." rows={3} value={w2} onChange={e=>setW2(e.target.value)} />
          </div>
          <div style={pvSt}><div style={{ fontSize:fs(8), textTransform:"uppercase", letterSpacing:".1em", color:C.cyan, marginBottom:3, fontWeight:700 }}>전체 송출 메시지 미리보기</div>{pv2}</div>
        </div>

        {/* 응급 */}
        <div style={secSt}>
          <div style={hdSt}><span style={numSt(C.violet)}>4</span> 응급 상황 안내 멘트 <span style={tagSt}>위험 감지 시</span></div>
          <div style={exSt}><div style={{ fontSize:fs(8), textTransform:"uppercase", letterSpacing:".1em", color:C.t3, marginBottom:3, fontWeight:700 }}>작성 예시</div>{DEFAULT_MSGS.emg}</div>
          <div style={{ marginBottom:9 }}>
            <textarea className="sg-input sg-input--textarea" placeholder="응급 상황 안내 문구를 입력하세요..." rows={3} value={emg} onChange={e=>setEmg(e.target.value)} />
          </div>
          <div style={pvSt}><div style={{ fontSize:fs(8), textTransform:"uppercase", letterSpacing:".1em", color:C.cyan, marginBottom:3, fontWeight:700 }}>전체 송출 메시지 미리보기</div>{pvE}</div>
        </div>

        <button className="sg-button-primary sg-button-primary--large" style={{ marginTop:6 }} onClick={save}>저장 후 모니터링 시작 →</button>
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
    <div style={{ background:C.bg, width:600, maxHeight:"90vh", overflowY:"auto", borderRadius:C.rXl, border:`1px solid ${C.bd2}`, display:"flex", flexDirection:"column" }}>
      <div style={{ padding:"16px 20px", borderBottom:`1px solid ${C.bd}`, background:C.sf, display:"flex", justifyContent:"space-between", alignItems:"center", position:"sticky", top:0, zIndex:10 }}>
        <div style={{ fontSize:fs(16), fontWeight:800, color:C.cyan }}>🚨 수정 창 🚨</div>
        <button className="sg-text-button" onClick={onClose}>✕ 닫기</button>
      </div>
      <div style={{ padding:"24px" }}>
        <div style={{ marginBottom:16 }}>
          <label className="sg-label">1차 경고 멘트 수정</label>
          <textarea className="sg-input sg-input--textarea" value={w1} onChange={e=>setW1(e.target.value)} />
        </div>
        <div style={{ marginBottom:16 }}>
          <label className="sg-label">2차 경고 멘트 수정</label>
          <textarea className="sg-input sg-input--textarea" value={w2} onChange={e=>setW2(e.target.value)} />
        </div>
        <div style={{ marginBottom:24 }}>
          <label className="sg-label">위험 감지 응급 멘트 수정</label>
          <textarea className="sg-input sg-input--textarea" value={emg} onChange={e=>setEmg(e.target.value)} />
        </div>
        <button className="sg-button-primary" onClick={save}>수정 내용 적용하기</button>
      </div>
    </div>
  )
}

/* ════════════════════════════════════════════════════════════
   SCREEN 3: 메인 대시보드
════════════════════════════════════════════════════════════ */
function MainScreen({ adminId, config, serverIP, onGoConfig, onLogout, onUpdateConfig, theme, onToggleTheme }) {
  const [status,   setStatus]   = useState(0)
  const [zoneStatusMap, setZoneStatusMap] = useState({})
  const [pausedZones, setPausedZones] = useState({})
  const [detected, setDetected] = useState(false)
  const [elapsed,  setElapsed]  = useState(0)
  const [personEl, setPersonEl] = useState(0)
  const [beats,    setBeats]    = useState({ background:0, speech:0, footsteps:0, interaction:0, impact_noise:0, emergency:0 })
  const [beatsTs,  setBeatsTs]  = useState("대기")
  const [lastSnd,  setLastSnd]  = useState("서버 연결 대기")
  const [curMsg,   setCurMsg]   = useState(null)
  const [decisionMeta, setDecisionMeta] = useState({
    situationName: "대기",
    source: "대기",
    reason: "서버 분석 결과를 기다리는 중입니다",
    action: "감시 대기",
    beatsLabel: "—",
    beatsRawLabel: "—",
    sttText: "",
    ttsKey: "NONE",
    emergencyConfirmed: false,
    timestamp: "대기",
  })
  const [logsByZone, setLogsByZone] = useState(() => {
    try { return JSON.parse(localStorage.getItem("sg-logs") || "{}") } catch { return {} }
  })
  const [clock,    setClock]    = useState(nowStr())
  const [systemUptime, setSystemUptime] = useState(0)
  const [sidebarExpanded, setSidebarExpanded] = useState({ status:false, health:false, zone:false, detection:false, logs:false })
  const toggleSidebarSection = useCallback((key) => setSidebarExpanded(prev => ({...prev, [key]:!prev[key]})), [])
  const wsRef = useRef(null)
  const reconnectRef = useRef(null)
  const geocodeCacheRef = useRef({})
  const mapPanelRef = useRef(null)
  const mapIframeRef = useRef(null)
  const mapStatusRef = useRef({})
  const cctvWindowRef = useRef(null)
  const [cctvWidthPercent, setCctvWidthPercent] = useState(40)
  const [cctvPopupOpen, setCctvPopupOpen] = useState(false)
  const [cctvLatchedActive, setCctvLatchedActive] = useState(false)
  const [cctvAlertStatus, setCctvAlertStatus] = useState(1)

  const [mentPopup, setMentPopup] = useState(false)
  const [mentEditModal, setMentEditModal] = useState(false)
  const [zoneModal, setZoneModal] = useState(false)
  const [mapInfoModal, setMapInfoModal] = useState(false)

  const [mapCoord, setMapCoord] = useState("37.5665° N, 126.9780° E")
  const [mapAddr, setMapAddr] = useState(config.zone || "관할 구역 주소 미상")
  const [settingsModal, setSettingsModal] = useState(false)
  const [notifPanelOpen, setNotifPanelOpen] = useState(false)
  const [notifications, setNotifications] = useState([])
  const [selfCheckRunning, setSelfCheckRunning] = useState(false)
  const [selfCheckResult, setSelfCheckResult] = useState(null)

  useEffect(() => {
    if (status !== 0) {
      setCctvLatchedActive(true)
      setCctvAlertStatus(status)
    }
  }, [status])

  useEffect(() => {
    if (!cctvPopupOpen) return

    const timer = setInterval(() => {
      if (cctvWindowRef.current && cctvWindowRef.current.closed) {
        cctvWindowRef.current = null
        setCctvPopupOpen(false)
      }
    }, 500)

    return () => clearInterval(timer)
  }, [cctvPopupOpen])

  const statusRef  = useRef(status)
  const pausedRef  = useRef(false)
  const configRef  = useRef(config)
  const adminRef   = useRef(adminId)
  const selectedZoneIdRef = useRef(null)
  const mapCoordRef = useRef(mapCoord)
  const mapAddrRef = useRef(mapAddr)
  const zonesRef = useRef([])
  statusRef.current = status
  configRef.current = config; adminRef.current  = adminId
  mapCoordRef.current = mapCoord
  mapAddrRef.current = mapAddr

  const startTime = useRef(nowStr())
  const API_BASE = normalizeServerBase(serverIP)
  const DASHBOARD_WS_URL = dashboardWsUrl(serverIP)
  const ZONE_LABELS = ["산", "공사장", "저수지", "강", "논"]

  /* 구역 */
  const [zones, setZones] = useState([])
  const [selectedZoneId, setSelectedZoneId] = useState(null)

  const _zoneKey = selectedZoneId || "default"
  const paused = !!pausedZones[_zoneKey]
  const logs = logsByZone[_zoneKey] || []

  pausedRef.current = paused

  const [newZoneName, setNewZoneName] = useState("")
  const [newZoneCoord, setNewZoneCoord] = useState("")
  const [newZoneAddr, setNewZoneAddr] = useState("")
  const [newZoneLabel, setNewZoneLabel] = useState("산")

  selectedZoneIdRef.current = selectedZoneId
  zonesRef.current = zones

  /* DB에서 구역 목록 로드 */
  useEffect(() => {
    fetch(`${API_BASE}/api/zones`)
      .then(r => r.json())
      .then(data => {
        const serverZones = Array.isArray(data) ? data.map(normalizeZoneFromServer) : []
        setZones(serverZones)
        if (serverZones.length > 0 && !selectedZoneId) {
          const first = serverZones[0]
          setSelectedZoneId(first.id)
          onUpdateConfig({ ...configRef.current, zone: first.name })
          setMapCoord(first.coord || "37.5665° N, 126.9780° E")
          setMapAddr(first.addr || first.label || "")
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!selectedZoneId && zones.length > 0) {
      const firstZone = zones[0]
      setSelectedZoneId(firstZone.id)
      onUpdateConfig({ ...configRef.current, zone: firstZone.name })
      setMapCoord(firstZone.coord || "37.5665° N, 126.9780° E")
      setMapAddr(firstZone.addr || firstZone.label || "")
    }
  }, [selectedZoneId, zones])

  const selectZone = (zone) => {
    const nextZone = normalizeZoneFromServer(zone)
    setSelectedZoneId(nextZone.id)
    onUpdateConfig({ ...configRef.current, zone: nextZone.name })
    setMapCoord(nextZone.coord || "37.5665° N, 126.9780° E")
    setMapAddr(nextZone.addr || nextZone.label || "")

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: "zone_select",
        zone_id: nextZone.id,
        zone_name: nextZone.name,
        coord: nextZone.coord,
        addr: nextZone.addr || nextZone.label,
      }))
    }

    addLog("sys", "구역 변경", `${nextZone.name} (${nextZone.addr || nextZone.label || "미분류"})`)
  }

  const addZone = () => {
    const name = newZoneName.trim()
    const coord = newZoneCoord.trim()
    if (!name) return

    const id = genId()
    const next = { id, name, coord, label: newZoneLabel }

    fetch(`${API_BASE}/api/zones`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(next),
    })
      .then(r => r.json())
      .then(saved => {
        const normalized = normalizeZoneFromServer(saved)
        setZones(prev => [...prev, normalized])
        selectZone(normalized)
      })
      .catch(() => {
        setZones(prev => [...prev, next])
        selectZone(next)
      })

    setNewZoneName("")
    setNewZoneCoord("")
    setNewZoneAddr("")
    setNewZoneLabel("산")
  }

  const [editingZoneId, setEditingZoneId] = useState(null)
  const [editName, setEditName]   = useState("")
  const [editLabel, setEditLabel] = useState("산")
  const [editCoord, setEditCoord] = useState("")

  const startEditZone = (zone) => {
    setEditingZoneId(zone.id)
    setEditName(zone.name)
    setEditLabel(zone.label || "산")
    setEditCoord(zone.coord || "")
  }

  const saveEditZone = () => {
    if (!editingZoneId || !editName.trim()) return
    const updated = { name: editName.trim(), label: editLabel, coord: editCoord.trim() }
    const normalized = normalizeZoneFromServer({ id: editingZoneId, ...updated })
    fetch(`${API_BASE}/api/zones/${editingZoneId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updated),
    }).catch(() => {})
    setZones(prev => prev.map(z => z.id === editingZoneId ? { ...z, ...normalized } : z))
    if (selectedZoneId === editingZoneId) {
      onUpdateConfig({ ...configRef.current, zone: updated.name })
      setMapCoord(updated.coord || mapCoord)
      setMapAddr(normalized.addr || normalized.label)
    }
    setEditingZoneId(null)
  }

  const deleteZone = (id) => {
    fetch(`${API_BASE}/api/zones/${id}`, { method: "DELETE" }).catch(() => {})

    const nextZones = zones.filter(z => z.id !== id)
    setZones(nextZones)

    if (selectedZoneId === id) {
      const nextZone = nextZones[0]
      if (nextZone) {
        selectZone(nextZone)
      } else {
        setSelectedZoneId(null)
        onUpdateConfig({ ...configRef.current, zone: "" })
        setMapCoord("37.5665° N, 126.9780° E")
        setMapAddr("")
      }
    }
  }

  /* 구역 전환 시 CCTV 초기화 */
  useEffect(() => {
    setCctvLatchedActive(false)
    setCctvPopupOpen(false)
  }, [selectedZoneId])

  /* 새 창이 닫혔는지 0.5초마다 확인 */
  useEffect(() => {
    if (!cctvPopupOpen) return
    const timer = setInterval(() => {
      if (cctvWindowRef.current && cctvWindowRef.current.closed) {
        cctvWindowRef.current = null
        setCctvPopupOpen(false)
      }
    }, 500)
    return () => clearInterval(timer)
  }, [cctvPopupOpen])

  /* 시계 */
  useEffect(() => {
    const iv = setInterval(() => setClock(nowStr()), 1000)
    return () => clearInterval(iv)
  }, [])

  /* 시스템 가동 시간 */
  useEffect(() => {
    const iv = setInterval(() => setSystemUptime(p => p + 1), 1000)
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

  const addLog = useCallback((type, title, detail, zoneId) => {
    const t = nowStr()
    const zId = zoneId || selectedZoneIdRef.current || "default"
    setLogsByZone(prev => {
      const next = {
        ...prev,
        [zId]: [{ id:Date.now()+Math.random(), t, type, title, detail }, ...(prev[zId] || [])].slice(0, 100)
      }
      try { localStorage.setItem("sg-logs", JSON.stringify(next)) } catch {}
      return next
    })
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

  const sendZonesSync = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: "zones_sync",
        zones: zonesRef.current.map(z => ({
          id: z.id,
          name: z.name,
          coord: z.coord,
          addr: z.addr || z.label || "",
        })),
      }))
    }
  }, [])

  const sendSelectedZoneToServer = useCallback((zone) => {
    if (!zone || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    wsRef.current.send(JSON.stringify({
      type: "zone_select",
      zone_id: zone.id,
      zone_name: zone.name,
      coord: zone.coord,
      addr: zone.addr || zone.label || "",
    }))
  }, [])

  useEffect(() => {
    const selected = zones.find(z => z.id === selectedZoneId)
    if (!selected) return
    sendZonesSync()
    sendSelectedZoneToServer(selected)
  }, [selectedZoneId, zones, sendZonesSync, sendSelectedZoneToServer])

  const pushOtherZoneNotification = useCallback((payload) => {
    const zoneId = payload.zone_id || payload.zoneId
    const incomingZoneName = payload.zone_name || payload.zoneName || ""
    const matchedZone = zonesRef.current.find(z => z.id === zoneId || z.name === incomingZoneName)
    const resolvedZoneId = matchedZone?.id || zoneId
    const zoneName = matchedZone?.name || (!looksLikeDeviceName(incomingZoneName) && incomingZoneName) || "관리구역 미지정"

    if (!resolvedZoneId) return

    const kind =
      payload.kind ||
      (payload.tts_key === "INTRUSION_WARN_2" ? "warn2" :
       payload.tts_key === "EMERGENCY_GUIDE" || payload.tts_key === "EVACUATION_GUIDE" ? "emergency" :
       "warn1")

    const type = payload.situation === 2 || kind === "emergency" ? 2 : 1

    setZoneStatusMap(prev => ({
      ...prev,
      [resolvedZoneId]: type,
    }))

    setNotifications(prev => [{
      id: Date.now() + Math.random(),
      zoneId: resolvedZoneId,
      zoneName,
      coord: matchedZone?.coord || payload.coord || payload.map_coord || "37.5665° N, 126.9780° E",
      addr: matchedZone?.addr || payload.addr || payload.address || zoneName,
      kind,
      type,
      title: kind === "emergency" ? "응급상황" : "무단침입",
      message:
        payload.message || payload.reason ||
        (kind === "warn1" ? "1차 경고 방송 송출" :
         kind === "warn2" ? "2차 경고 방송 송출" :
         "응급 안내 방송 송출"),
      time: payload.timestamp || nowStr(),
      read: false,
    }, ...prev].slice(0, 30))
  }, [])

  useEffect(() => {
    let closed = false

    const connect = () => {
      const ws = new WebSocket(DASHBOARD_WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        console.log("✅ 서버 연결 성공")
        addLog("sys", "백엔드 연결 성공", DASHBOARD_WS_URL)
        sendTtsConfig()
        sendZonesSync()

        const currentZone =
          zonesRef.current.find(z => z.id === selectedZoneIdRef.current) ||
          zonesRef.current[0]

        if (currentZone) {
          selectedZoneIdRef.current = currentZone.id
          setSelectedZoneId(currentZone.id)
          onUpdateConfig({ ...configRef.current, zone: currentZone.name })
          setMapCoord(currentZone.coord)
          setMapAddr(currentZone.addr || currentZone.label || "")

          ws.send(JSON.stringify({
            type: "zone_select",
            zone_id: currentZone.id,
            zone_name: currentZone.name,
            coord: currentZone.coord,
            addr: currentZone.addr || currentZone.label || "",
          }))
        }
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        console.log("📡 서버 데이터:", data)

        if (data.type === "zone_alert") {
          pushOtherZoneNotification(data)
          return
        }

        if (data.type === "status") {
          if (data.message === "paused") {
            const zId = data.zone_id || selectedZoneIdRef.current || "default"
            setPausedZones(prev => ({ ...prev, [zId]: true }))
          }
          return
        }

        if (data.type === "pause_state") {
          const zId = data.zone_id || selectedZoneIdRef.current || "default"
          setPausedZones(prev => ({ ...prev, [zId]: Boolean(data.paused) }))
          addLog("sys", data.paused ? "감지 일시정지 적용" : "감지 재개 적용", "백엔드 반영 완료")
          return
        }
        if (data.type === "self_check_result") {
          setSelfCheckRunning(false)
          setSelfCheckResult(data.items || [])
          addLog("sys", "자가진단 완료", "백엔드 점검 결과 수신")
          return
        }
        if (data.type && data.type !== "analysis") return

        const situation = Number(data.situation ?? 0)
        const rawIncomingZoneId =
          data.zone_id ||
          data.zoneId ||
          selectedZoneIdRef.current
        const incomingZoneId =
          !rawIncomingZoneId || rawIncomingZoneId === "default"
            ? (selectedZoneIdRef.current || "default")
            : rawIncomingZoneId

        if (incomingZoneId) {
          setZoneStatusMap(prev => ({
            ...prev,
            [incomingZoneId]: situation,
          }))
        }

        if (incomingZoneId && selectedZoneIdRef.current && incomingZoneId !== selectedZoneIdRef.current) return

        if (true) {
          setStatus(situation)
          setBeatsTs(data.timestamp || nowStr())
          const fallbackBeats = {
            background:   situation === 0 ? 90 : 5,
            speech:       0,
            footsteps:    0,
            interaction:  0,
            impact_noise: situation === 2 ? 80 : 0,
            emergency:    0,
          }
          const nextBeats = data.beats || fallbackBeats
          const emergencyActive = Boolean(
            data.emergency_voice_confirmed ||
            (situation === 2 && data.decision_source === "gpt")
          )
          setBeats({
            ...fallbackBeats,
            ...nextBeats,
            emergency: Number(nextBeats.emergency ?? (emergencyActive ? 100 : 0)),
          })
          const rawSoundLabel = data.stt_text?.trim() ? "speech" : (data.beats_raw_label || data.beats_label || "—")
          setLastSnd(SOUND_LABEL_TEXT[rawSoundLabel] || rawSoundLabel)
          setDecisionMeta({
            situationName: data.situation_name || STATUS_DATA[situation]?.name || "분석 결과",
            source: data.decision_source || "rule",
            reason: data.reason || "",
            action: data.action || "",
            beatsLabel: SOUND_LABEL_TEXT[data.beats_label] || data.beats_label || "—",
            beatsRawLabel: SOUND_LABEL_TEXT[data.beats_raw_label] || data.beats_raw_label || "—",
            sttText: data.stt_text || "",
            ttsKey: data.tts_key || "NONE",
            emergencyConfirmed: emergencyActive,
            timestamp: data.timestamp || nowStr(),
          })
        }

        const activeZone = zonesRef.current.find(z => z.id === selectedZoneIdRef.current)
        const activeZoneCoord = activeZone?.coord || mapCoordRef.current
        const activeZoneAddr = activeZone?.addr || mapAddrRef.current

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

        // 서버 채널 분리로 받은 이벤트는 현재 구역 것 → zone_id 없이 addLog
        addLog(
          situation === 2 ? 2 : situation === 1 ? 1 : "n",
          eventTitle,
          data.stt_text?.trim()
            ? `음성 감지: "${data.stt_text.trim()}"`
            : data.reason || ""
        )

        if (data.stt_text && data.stt_text.trim()) {
          addLog("voice", "음성 인식 결과", `"${data.stt_text.trim()}"`)
        }

        // 다른 구역 알림은 서버가 zone_alert 타입으로 별도 전송하므로 제거
        if (false && noticeKind) {
          setNotifications(prev => [{
            id: Date.now() + Math.random(),
            zoneId: data.zone_id,
            zoneName: data.zone_name || "관리구역 미지정",
            coord: data.coord || activeZoneCoord,
            addr: data.addr || activeZoneAddr,
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
          addLog(type === "응급 안내 방송" ? "emg" : "warn", `${type} 송출`, msg, data.zone_id)
        } else {
          setCurMsg(null)
        }
      }

      ws.onerror = (err) => {
        console.error("WebSocket 에러:", err)
      }

      ws.onclose = () => {
        if (closed) return
        setStatus(0)
        setDetected(false)
        setCurMsg(null)
        setDecisionMeta({
          situationName: "대기",
          source: "연결 끊김",
          reason: "백엔드 연결이 끊겨 재연결을 기다리는 중입니다",
          action: "재연결 대기",
          beatsLabel: "—",
          beatsRawLabel: "—",
          sttText: "",
          ttsKey: "NONE",
          emergencyConfirmed: false,
          timestamp: "연결 끊김",
        })
        setBeats({ background:0, speech:0, footsteps:0, interaction:0, impact_noise:0, emergency:0 })
        setBeatsTs("연결 끊김")
        setLastSnd("서버 연결 끊김")
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
  }, [addLog, sendTtsConfig, sendZonesSync, pushOtherZoneNotification])

  useEffect(() => {
    sendZonesSync()
  }, [zones, sendZonesSync])

  useEffect(() => {
    const statuses = {}
    zones.forEach(z => {
      statuses[z.id] = z.id === selectedZoneId ? status : (zoneStatusMap[z.id] ?? 0)
    })
    if (zones.length === 0) statuses["default"] = status
    mapStatusRef.current = statuses
    mapIframeRef.current?.contentWindow?.postMessage({ type: "zone_status", statuses }, "*")
  }, [status, zoneStatusMap, zones, selectedZoneId])

  const togglePause = () => {
    const zoneId = selectedZoneIdRef.current || "default"
    const next = !pausedRef.current
    setPausedZones(prev => ({ ...prev, [zoneId]: next }))

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "pause", paused: next, zone_id: zoneId }))
      addLog("sys", next ? "감지 일시정지 요청" : "감지 재개 요청", `관리자 ${adminRef.current}`)
    } else {
      addLog("sys", "서버 미연결", "WebSocket 연결 후 다시 시도하세요")
    }
  }

  const visibleNotifications = notifications.filter(n => n.zoneId !== selectedZoneId)
  const unreadCount = visibleNotifications.filter(n => !n.read).length

  const switchToZone = (notice) => {
    const zone = zones.find(z => z.id === notice.zoneId || z.name === notice.zoneName)
    if (zone) {
      selectZone(zone)
    } else {
      onUpdateConfig({ ...configRef.current, zone: notice.zoneName || "관리구역 미지정" })
      setMapCoord(notice.coord || "37.5665° N, 126.9780° E")
      setMapAddr(notice.addr || notice.zoneName || "관할 구역 주소 미상")
    }
    setNotifications(prev => prev.map(n => n.id === notice.id ? { ...n, read: true } : n))
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

  const isCoordinateInput = (input) => {
    const nums = String(input).match(/-?\d+(\.\d+)?/g)
    return nums && nums.length >= 2
  }

  const toCoordText = (lat, lon) =>
    `${Number(lat).toFixed(6)}° N, ${Number(lon).toFixed(6)}° E`

  const geocodeAddress = async (input) => {
    const q = String(input || "").trim()
    if (!q) throw new Error("검색어 없음")
    if (geocodeCacheRef.current[q]) return geocodeCacheRef.current[q]

    const res = await fetch(`http://${serverIP}/api/geocode?q=${encodeURIComponent(q)}`)
    if (!res.ok) throw new Error("주소/장소 검색 실패")

    const result = await res.json()
    if (!Number.isFinite(Number(result.lat)) || !Number.isFinite(Number(result.lon)))
      throw new Error("좌표 응답 오류")

    const normalized = { lat: Number(result.lat), lon: Number(result.lon), addr: result.addr || q }
    geocodeCacheRef.current[q] = normalized
    return normalized
  }

  const reverseGeocode = async (lat, lon) => {
    const key = `reverse:${Number(lat).toFixed(6)},${Number(lon).toFixed(6)}`
    if (geocodeCacheRef.current[key]) return geocodeCacheRef.current[key].addr || ""
    try {
      const res = await fetch(
        `http://${serverIP}/api/reverse-geocode?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`
      )
      if (!res.ok) return ""
      const data = await res.json()
      const addr = data.addr || data.address || ""
      geocodeCacheRef.current[key] = { lat: Number(lat), lon: Number(lon), addr }
      return addr
    } catch { return "" }
  }

  const applyLocationInput = async (input) => {
    const value = String(input || "").trim()
    if (!value) return
    try {
      let lat, lon, addr
      if (isCoordinateInput(value)) {
        const nums = value.match(/-?\d+(\.\d+)?/g)
        lat = Number(nums[0]); lon = Number(nums[1])
        addr = await reverseGeocode(lat, lon)
      } else {
        const result = await geocodeAddress(value)
        lat = result.lat; lon = result.lon; addr = result.addr
      }
      const coordText = toCoordText(lat, lon)
      setMapCoord(coordText)
      setMapAddr(addr || "")
      if (selectedZoneId) {
        setZones(prev => prev.map(z =>
          z.id === selectedZoneId ? { ...z, coord: coordText, addr: addr || "" } : z
        ))
      }
    } catch (e) {
      console.error(e)
      alert("주소 또는 좌표를 찾지 못했습니다. 도로명 주소나 정확한 좌표를 입력해 주세요.")
    }
  }

  const applyCoordInput = async (input) => {
    const value = String(input || "").trim()
    if (!value) return
    if (!isCoordinateInput(value)) {
      alert("GPS 좌표 칸에는 좌표만 입력해 주세요. 예: 37.5665, 126.9780")
      return
    }
    const nums = value.match(/-?\d+(\.\d+)?/g)
    const lat = Number(nums[0]); const lon = Number(nums[1])
    const coordText = toCoordText(lat, lon)
    const addr = await reverseGeocode(lat, lon)
    setMapCoord(coordText)
    if (addr) setMapAddr(addr)
    if (selectedZoneId) {
      setZones(prev => prev.map(z =>
        z.id === selectedZoneId ? { ...z, coord: coordText, addr: addr || z.addr || "" } : z
      ))
    }
  }

  const applyNewZoneLocationInput = async (input) => {
    const value = String(input || "").trim()
    if (!value) return
    try {
      let lat, lon, addr
      if (isCoordinateInput(value)) {
        const nums = value.match(/-?\d+(\.\d+)?/g)
        lat = Number(nums[0]); lon = Number(nums[1])
        addr = await reverseGeocode(lat, lon)
      } else {
        const result = await geocodeAddress(value)
        lat = result.lat; lon = result.lon; addr = result.addr
      }
      setNewZoneCoord(toCoordText(lat, lon))
      setNewZoneAddr(addr || "")
    } catch (e) {
      console.error(e)
      alert("새 구역 주소 또는 좌표를 찾지 못했습니다.")
    }
  }

  const cctvEventActive = cctvLatchedActive
  const cctvVisible = cctvEventActive && !cctvPopupOpen
  const cctvVideoSrc = "/test_video.mp4"
  const cctvStatus = cctvAlertStatus || 1

  const closeCctvView = () => {
    setCctvLatchedActive(false)
    setCctvPopupOpen(false)
    if (cctvWindowRef.current && !cctvWindowRef.current.closed) {
      cctvWindowRef.current.close()
    }
    cctvWindowRef.current = null
  }

  const openCctvPopup = () => {
    const existingWindow = cctvWindowRef.current
    if (existingWindow && !existingWindow.closed) {
      existingWindow.focus()
      setCctvPopupOpen(true)
      return
    }
    const popup = window.open(
      "",
      "soundguard-cctv-popup",
      "popup=yes,width=1120,height=680,left=120,top=80,resizable=yes,scrollbars=no"
    )
    if (!popup) {
      alert("팝업이 차단되었습니다. 브라우저 팝업 허용 후 다시 눌러주세요.")
      return
    }
    const videoUrl = new URL(cctvVideoSrc, window.location.origin).href
    const accentColor = cctvStatus === 2 ? "var(--sg-red)" : "var(--sg-amber)"
    const statusText = cctvStatus === 2 ? "위험 감지" : "무단침입 감지"
    popup.document.open()
    popup.document.write(`
      <!doctype html><html lang="ko">
        <head><meta charset="utf-8" /><title>SoundGuard CCTV</title>
          <style>
            :root {
              --sg-popup-fs-11: 11px; --sg-popup-fs-12: 12px; --sg-popup-fs-13: 13px;
              --sg-font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
              --sg-video-bg: #020711; --sg-text: #deeaff; --sg-text-muted: #7090ae;
              --sg-border: #162c44; --sg-cyan: #22d3ee; --sg-cyan-border: rgba(34,211,238,.35);
              --sg-red: #f87171; --sg-amber: #fbbf24; --sg-header-bg: rgba(7,14,28,.98);
              --sg-panel-muted: rgba(255,255,255,.05); --sg-panel-overlay: rgba(2,7,17,.82);
              --sg-radius-md: 6px; --sg-radius-lg: 8px; --sg-radius-pill: 999px;
            }
            @media (max-width: 1280px) { :root { --sg-popup-fs-11: 10px; --sg-popup-fs-12: 11px; --sg-popup-fs-13: 12px; } }
            @media (min-width: 1600px) { :root { --sg-popup-fs-11: 12px; --sg-popup-fs-12: 13px; --sg-popup-fs-13: 14px; } }
            * { box-sizing: border-box; }
            html, body { width:100%; height:100%; margin:0; background:var(--sg-video-bg); color:var(--sg-text); font-family:var(--sg-font-sans); overflow:hidden; }
            .wrap { width:100%; height:100%; display:flex; flex-direction:column; }
            .bar { height:44px; display:flex; align-items:center; gap:10px; padding:0 14px; background:var(--sg-header-bg); border-bottom:1px solid var(--sg-border); flex-shrink:0; }
            .dot { width:8px; height:8px; border-radius:var(--sg-radius-pill); background:${accentColor}; box-shadow:0 0 14px ${accentColor}; }
            .title { font-size:var(--sg-popup-fs-13); font-weight:900; color:${accentColor}; }
            .status { font-size:var(--sg-popup-fs-11); color:var(--sg-text-muted); }
            .spacer { margin-left:auto; }
            .control { background:var(--sg-panel-muted); border:1px solid var(--sg-border); border-radius:var(--sg-radius-md); padding:6px 10px; color:var(--sg-text); cursor:pointer; font-size:var(--sg-popup-fs-11); font-weight:800; }
            .control:hover { border-color:var(--sg-cyan); color:#fff; }
            .viewer { position:relative; width:100%; flex:1; min-height:0; }
            .fcbtn { position:absolute; right:14px; bottom:14px; background:var(--sg-panel-overlay); border:1px solid var(--sg-cyan-border); border-radius:var(--sg-radius-lg); padding:8px 12px; color:var(--sg-text); cursor:pointer; font-size:var(--sg-popup-fs-12); font-weight:900; }
            .fcbtn:hover { border-color:var(--sg-cyan); }
            .exit-fs { display:none; }
            :fullscreen .enter-fs { display:none; }
            :fullscreen .exit-fs { display:block; }
            video { width:100%; height:100%; object-fit:cover; display:block; background:var(--sg-video-bg); }
          </style>
        </head>
        <body>
          <div class="wrap">
            <div class="bar">
              <span class="dot"></span>
              <span class="title">SoundGuard CCTV</span>
              <span class="status">${statusText}</span>
              <span class="spacer"></span>
              <button class="control" onclick="window.close()">닫기</button>
            </div>
            <div class="viewer">
              <video src="${videoUrl}" autoplay muted loop playsinline controls></video>
              <button class="fcbtn enter-fs" onclick="document.documentElement.requestFullscreen&&document.documentElement.requestFullscreen()">전체화면</button>
              <button class="fcbtn exit-fs" onclick="document.exitFullscreen&&document.exitFullscreen()">원래크기</button>
            </div>
          </div>
        </body>
      </html>
    `)
    popup.document.close()
    popup.focus()
    cctvWindowRef.current = popup
    setCctvPopupOpen(true)
  }

  const startCctvResize = (event) => {
    event.preventDefault()
    const panel = mapPanelRef.current
    if (!panel) return
    const rect = panel.getBoundingClientRect()
    const origCursor = document.body.style.cursor
    const origSelect = document.body.style.userSelect
    const updateWidth = (clientX) => {
      const next = ((rect.right - clientX) / rect.width) * 100
      setCctvWidthPercent(Math.min(65, Math.max(25, next)))
    }
    const onMove = (e) => updateWidth(e.clientX)
    const onStop = () => {
      document.body.style.cursor = origCursor
      document.body.style.userSelect = origSelect
      document.removeEventListener("pointermove", onMove)
      document.removeEventListener("pointerup", onStop)
      document.removeEventListener("pointercancel", onStop)
    }
    document.body.style.cursor = "col-resize"
    document.body.style.userSelect = "none"
    updateWidth(event.clientX)
    document.addEventListener("pointermove", onMove)
    document.addEventListener("pointerup", onStop)
    document.addEventListener("pointercancel", onStop)
  }

  const sd = STATUS_DATA[status]

  const parseCoord = (coord) => {
    const nums = String(coord).match(/-?\d+(\.\d+)?/g)
    return { lat: nums?.[0] || "37.5665", lon: nums?.[1] || "126.9780" }
  }

  const { lat, lon } = parseCoord(mapCoord)
  const selectedZone = zones.find(z => z.id === selectedZoneId)
  const currentZoneName = selectedZone?.name || config.zone || "관리구역 미지정"
  const zonesForMap = zones.length > 0
    ? zones.map(z => ({
        id: z.id,
        name: z.name,
        coord: z.coord,
        addr: z.addr || z.label || "",
        status: 0,
        selected: z.id === selectedZoneId,
      }))
    : [{
        id: "default",
        name: currentZoneName,
        coord: mapCoord || `${lat}, ${lon}`,
        addr: mapAddr || "관할 구역 주소 미상",
        status: 0,
        selected: true,
      }]
  const mapPayloadZones = zonesForMap.map(z =>
    z.id === "default" ? { ...z, addr: mapAddr || "관할 구역 주소 미상" } : z
  )
  const mapSrc =
    `/map.html?zones=${encodeURIComponent(JSON.stringify(mapPayloadZones))}` +
    `&key=${encodeURIComponent(VWORLD_KEY || "")}`
  

  const mapPanelSt = {
    flex:1, display:"flex", flexDirection:"column",
    border:`1px solid ${C.bd}`, borderRadius:C.rLg,
    position:"relative", background:"#0a1424", minHeight:0, overflow:"hidden",
  }
  const mapAreaSt = { position:"relative", flex:1, minWidth:0, minHeight:0, overflow:"hidden" }
  const resizeHandleSt = {
    position:"relative", zIndex:4, cursor:"col-resize",
    background:`linear-gradient(90deg, ${C.bd}, ${C.cyanSoft}, ${C.bd})`,
    borderLeft:`1px solid ${C.bd}`, borderRight:`1px solid ${C.bd}`,
    display:"flex", alignItems:"center", justifyContent:"center", touchAction:"none",
  }
  const resizeGripSt = { width:2, height:44, borderRadius:2, background:"rgba(222,234,255,.45)", boxShadow:"0 0 12px rgba(34,211,238,.35)" }
  const cctvAreaSt = { position:"relative", minWidth:0, minHeight:0, overflow:"hidden", background:"#020711" }
  const bottomLayoutSt = cctvVisible
    ? { display:"grid", gridTemplateColumns:"minmax(540px,1fr) minmax(360px,36%)", gap:10, minHeight:280, maxHeight:"42%", flexShrink:0, minWidth:0 }
    : { display:"grid", gridTemplateColumns:"1fr", gap:10, flexShrink:0, minHeight:200, minWidth:0 }
  const bottomLeftLayoutSt = {
    display:"grid",
    gridTemplateColumns: cctvVisible ? "minmax(230px,.85fr) minmax(280px,1fr)" : "minmax(300px,.85fr) minmax(420px,1.35fr)",
    gap:10, minWidth:0, minHeight:0,
  }
  const cctvBottomAreaSt = { ...cctvAreaSt, minHeight:260, height:"100%" }

  const soundItems = [
    { key:"background",  label:"배경음",     value:Number(beats.background  || 0), color:C.green  },
    { key:"speech",      label:"사람 목소리", value:Number(beats.speech      || 0), color:C.cyan   },
    { key:"footsteps",   label:"발소리",      value:Number(beats.footsteps   || 0), color:C.amber  },
    { key:"interaction", label:"문소리",      value:Number(beats.interaction || 0), color:C.violet },
    { key:"impact_noise",label:"충격음",      value:Number(beats.impact_noise|| 0), color:C.red    },
    { key:"emergency",   label:"응급음",      value:Number(beats.emergency   || 0), color:C.red    },
  ]
  const dominantSound = soundItems.reduce((best, item) => item.value > best.value ? item : best, soundItems[0])
  const dominantSoundValue = Math.round(Math.max(0, Math.min(100, Number(dominantSound.value) || 0)))
  const decisionBadgeText = status === 2 ? "위험 감지" : status === 1 ? "무단침입 후보" : "정상 관제"
  const sttDisplay = decisionMeta.sttText?.trim() || "없음"
  const responseStateText = curMsg ? curMsg.type : status === 2 ? "위험 상황 확인 중" : status === 1 ? "경고 조건 확인 중" : "송출 대기"

  const mBtnSt = { border:`1px solid ${C.bd}`, borderRadius:C.rSm, padding:"4px 9px", background:"none", color:C.t2, cursor:"pointer", fontFamily:"inherit", fontSize:fs(10), whiteSpace:"nowrap" }

  const sidebarStatusMetrics = [
    ["판단 근거", decisionMeta.source || "대기", C.t2],
    ["대응 방침", decisionMeta.action || "감시 대기", sd.c],
    ["감지음", lastSnd, C.t2],
    ["타임스탬프", decisionMeta.timestamp || "대기", C.t3],
  ]

  const visibleHealthItems = [
    ["마이크", "연결됨", C.green],
    ["BEATs", beatsTs !== "대기" ? "활성" : "대기중", beatsTs !== "대기" ? C.green : C.amber],
    ["TTS", "준비됨", C.green],
    ["서버", status === 0 && beatsTs === "대기" ? "대기중" : "연결됨", status === 0 && beatsTs === "대기" ? C.amber : C.green],
  ]

  const visibleZoneInfoRows = [
    ["구역", currentZoneName, () => setZoneModal(true)],
    ["감지 장치", "마이크 #1", null],
    ["모니터링 시작", startTime.current, null],
  ]

  const visibleLogs = sidebarExpanded.logs ? logs : logs.slice(0, 8)

  return (
    <div style={{ display:"flex", flexDirection:"column", height:"100vh", overflow:"hidden", position:"relative" }}>

      {/* ── 헤더 ── */}
      <div className="sg-dashboard-header">
        <div style={{ display:"flex", alignItems:"center", gap:8 }}>
          <div style={{ fontSize:fs(14), fontWeight:800, whiteSpace:"nowrap" }}><span style={{display:"inline-flex",alignItems:"center",gap:6}}><img src="/SoundGuardLogo.png" alt="SoundGuard" style={{ width:34, height:34, objectFit:"contain" }} />SoundGuard</span></div>
          <div className="sg-chip"><span style={{display:"inline-flex",alignItems:"center",gap:4}}><User size={11} />{adminId}</span></div>
          <div style={{ display:"flex", alignItems:"center", gap:6, padding:"3px 10px", background:C.panel2, border:`1px solid ${C.bd}`, borderRadius:C.rPill }}>
            <span style={{ display:"inline-block", width:5, height:5, borderRadius:"50%", background:paused?C.amber:C.green, flexShrink:0 }} />
            <span style={{ fontSize:fs(10), color:C.t3 }}>{paused?"감지 일시정지":"시스템 활성"}</span>
            <span style={{ fontSize:fs(10), fontFamily:C.mono, color:C.t2 }}>{fmtUptime(systemUptime)}</span>
          </div>
        </div>

        {/* 중앙 현재 송출 메시지 */}
        <div style={{ position:"absolute", left:"50%", top:"50%", transform:"translate(-50%,-50%)", display:"flex", alignItems:"center", gap:8, background:curMsg ? C.panel2 : "transparent", border:`1px solid ${curMsg ? C.cyanBorder : C.bd}`, borderRadius:C.rPill, padding:"5px 18px", maxWidth:420, overflow:"hidden", pointerEvents:"none", zIndex:2, transition:"border-color 0.3s, background 0.3s" }}>
          <span style={{ width:6, height:6, borderRadius:"50%", background:curMsg ? C.cyan : C.t3, flexShrink:0, boxShadow: curMsg ? `0 0 8px ${C.cyan}` : "none", transition:"background 0.3s" }} />
          {curMsg ? (
            <>
              <span style={{ display:"inline-flex", alignItems:"center", gap:4, fontSize:fs(9), fontWeight:900, color:C.cyan, whiteSpace:"nowrap", flexShrink:0 }}><Megaphone size={11} />송출 중</span>
              <span style={{ fontSize:fs(10), color:C.t1, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{curMsg.text}</span>
            </>
          ) : (
            <span style={{ fontSize:fs(9), color:C.t3, whiteSpace:"nowrap" }}>송출 대기</span>
          )}
        </div>

        <div style={{ marginLeft:"auto", display:"flex", alignItems:"center", gap:5, flexWrap:"wrap" }}>
          <button className="sg-mini-button" onClick={togglePause} style={{ color:paused?C.green:C.amber, borderColor:paused?C.greenBorder:C.amberBorder, background:paused?C.greenSoft:C.amberSoft }}>
            <span style={{display:"inline-flex",alignItems:"center",gap:4}}>{paused ? <><Play size={11} />감지 재개</> : <><Pause size={11} />감지 일시정지</>}</span>
          </button>
          <button className="sg-mini-button" onClick={() => setMentPopup(true)} style={{ color:C.t1, background:C.panel2 }}>
            <span style={{display:"inline-flex",alignItems:"center",gap:4}}><FileText size={11} />안내멘트 설정</span>
          </button>
          <button
            onClick={() => setNotifPanelOpen(p => !p)}
            className="sg-mini-button"
            style={{ position:"relative", color: unreadCount > 0 ? C.cyan : C.t2, borderColor: unreadCount > 0 ? C.cyanBorder : C.bd, background: unreadCount > 0 ? C.cyanSoft : "none" }}
          >
            <span style={{display:"inline-flex",alignItems:"center",gap:4}}><Bell size={11} />알림</span>
            {unreadCount > 0 && (
              <span style={{ marginLeft:5, background:C.red, color:"#fff", borderRadius:C.rPill, fontSize:fs(9), fontWeight:800, padding:"1px 5px", lineHeight:"15px", display:"inline-block", verticalAlign:"middle" }}>
                {unreadCount}
              </span>
            )}
          </button>
          <button style={{ ...mBtnSt }} onClick={() => setSettingsModal(true)}><span style={{display:"inline-flex",alignItems:"center",gap:4}}><Settings size={11} />설정</span></button>
        </div>
      </div>

      {/* ── 바디 ── */}
      <div ref={mapPanelRef} style={{ position:"relative", flex:1, overflow:"hidden", minHeight:0 }}>

        {/* 지도 배경 - 전체화면 */}
        <iframe
          ref={mapIframeRef}
          key={mapSrc}
          title="SoundGuard Map"
          src={mapSrc}
          style={{ position:"absolute", inset:0, width:"100%", height:"100%", border:"none", display:"block" }}
          onLoad={() => {
            setTimeout(() => {
              mapIframeRef.current?.contentWindow?.postMessage(
                { type: "zone_status", statuses: mapStatusRef.current }, "*"
              )
            }, 400)
          }}
        />

        {/* 좌측 플로팅 패널 */}
        <div className="sg-left-float">

          <div className="sg-sidebar-node">
            <div>
              <div className="sg-sidebar-kicker">CONTROL NODE</div>
              <div className="sg-sidebar-node-title">{currentZoneName || "관리구역 미지정"}</div>
            </div>
            <span
              className="sg-sidebar-live"
              style={{
                color: paused ? C.amber : C.green,
                borderColor: paused ? C.amberBorder : C.greenBorder,
                background: paused ? C.amberSoft : C.greenSoft,
              }}
            >
              {paused ? "PAUSED" : "LIVE"}
            </span>
          </div>

          {/* 상태 배너 */}
          <div className="sg-sidebar-status" style={{ borderColor:sd.bd, background:sd.bg, color:sd.c }}>
            <div className="sg-sidebar-status-top">
              <div style={{ width:38, height:38, borderRadius:C.rMd, background:C.panel3, display:"flex", alignItems:"center", justifyContent:"center", flexShrink:0 }}><sd.Ico size={22} color={sd.c} /></div>
              <div className="sg-sidebar-status-copy">
                <div style={{ fontSize:fs(8), textTransform:"uppercase", letterSpacing:".15em", fontWeight:700, color:sd.c, marginBottom:3 }}>{sd.tag}</div>
                <div style={{ fontSize:fs(18), fontWeight:800, letterSpacing:"-.02em", color:sd.c }}>{sd.name}</div>
                {sidebarExpanded.status && <div style={{ fontSize:fs(11), color:C.t2, marginTop:2 }}>{sd.desc}</div>}
              </div>
              <button
                className="sg-sidebar-toggle"
                onClick={() => toggleSidebarSection("status")}
                aria-expanded={sidebarExpanded.status}
              >
                {sidebarExpanded.status ? "간단히" : "자세히"}
              </button>
            </div>
            {sidebarExpanded.status && (
              <>
                {status !== 0 && (
                  <div style={{ marginTop:6 }}>
                    <div style={{ fontSize:fs(8), textTransform:"uppercase", letterSpacing:".1em", color:C.t3 }}>발생 후 경과</div>
                    <div style={{ fontSize:fs(22), fontWeight:800, fontFamily:C.mono, color:sd.c }}>{fmt(elapsed)}</div>
                  </div>
                )}
                <div className="sg-sidebar-status-grid">
                  {sidebarStatusMetrics.map(([label, value, color]) => (
                    <div className="sg-sidebar-metric" key={label}>
                      <div className="sg-sidebar-metric-label">{label}</div>
                      <div className="sg-sidebar-metric-value" style={{ color }}>{value}</div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          <div className="sg-card sg-sidebar-card" style={{ flexShrink:0 }}>
            <div className="sg-panel-head">
              <span className="sg-panel-title">SYSTEM HEALTH</span>
            </div>
            <div className="sg-health-grid">
              {visibleHealthItems.map(([label, value, color]) => (
                <div className="sg-health-item" key={label}>
                  <span className="sg-health-dot" style={{ background:color, boxShadow:`0 0 10px ${color}` }} />
                  <span className="sg-health-label">{label}</span>
                  <span className="sg-health-value" style={{ color }}>{value}</span>
                </div>
              ))}
            </div>
          </div>

          {/* 구역 정보 */}
          <div className="sg-card sg-sidebar-card" style={{ flexShrink:0 }}>
            <div className="sg-panel-head">
              <span className="sg-panel-title" style={{display:"inline-flex",alignItems:"center",gap:5}}><MapPin size={13} />구역 정보</span>
            </div>
            <div style={{ display:"flex", flexDirection:"column" }}>
              {visibleZoneInfoRows.map(([l, v, handler]) => (
                <div
                  key={l}
                  style={{ padding:"10px 12px", borderBottom:`1px solid ${C.bd}`, cursor: handler ? "pointer" : "default", transition:"background-color 0.2s" }}
                  onMouseOver={e => { if(handler) { e.currentTarget.style.backgroundColor=C.cyanSoft; e.currentTarget.children[1].style.color=C.cyan } }}
                  onMouseOut={e => { if(handler) { e.currentTarget.style.backgroundColor="transparent"; e.currentTarget.children[1].style.color=C.t1 } }}
                  onClick={() => handler && handler()}
                >
                  <div style={{ fontSize:fs(8), textTransform:"uppercase", letterSpacing:".12em", color:C.t3, marginBottom:4, fontWeight:700 }}>{l}</div>
                  <div style={{ fontSize:fs(12), fontWeight:700, transition:"color 0.2s" }}>{v}</div>
                </div>
              ))}
            </div>
          </div>

          {/* 감지된 인물 */}
          <div className="sg-card sg-sidebar-card" style={{ flexShrink:0 }}>
            <div className="sg-panel-head">
              <span className="sg-panel-title" style={{display:"inline-flex",alignItems:"center",gap:5}}><User size={13} />감지된 인물</span>
              <div className="sg-panel-actions">
                <span style={{ fontSize:fs(8), padding:"2px 6px", border:`1px solid ${detected?C.amberBorder:C.bd}`, borderRadius:C.rXs, fontWeight:700, background:detected?C.amberSoft:C.panel2, color:detected?C.amber:C.t3 }}>{detected?"감지 중":"미감지"}</span>
                <button
                  className="sg-sidebar-toggle"
                  onClick={() => toggleSidebarSection("detection")}
                  aria-expanded={sidebarExpanded.detection}
                >
                  {sidebarExpanded.detection ? "간단히" : "자세히"}
                </button>
              </div>
            </div>
            <div style={{ padding:"10px 12px" }}>
              <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:sidebarExpanded.detection ? 10 : 0 }}>
                <div style={{ position:"relative", width:9, height:9, borderRadius:C.rPill, background:detected?C.amber:C.t3, flexShrink:0 }} />
                <div>
                  <div style={{ fontSize:fs(12), fontWeight:700 }}>{detected?"인원 감지됨":"감지 없음"}</div>
                  <div style={{ fontSize:fs(10), color:C.t2, marginTop:1 }}>{detected?"구역 내 비허가 인원 존재":"현재 구역 내 인원 없음"}</div>
                </div>
              </div>
              {sidebarExpanded.detection && (
                <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
                  {[["구역 내 체류", fmt(personEl)], ["마지막 감지음", lastSnd]].map(([l,v])=>(
                    <div key={l} style={{ background:C.panel, borderRadius:C.rSm, padding:"7px 9px", display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                      <div style={{ fontSize:fs(8), textTransform:"uppercase", letterSpacing:".1em", color:C.t3, fontWeight:700 }}>{l}</div>
                      <div style={{ fontSize:fs(11), fontWeight:700, fontFamily:C.mono }}>{v}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* 이벤트 로그 */}
          <div className="sg-card sg-sidebar-card sg-sidebar-log-card" style={{ flex:1, display:"flex", flexDirection:"column", minHeight:sidebarExpanded.logs ? 400 : 170 }}>
            <div className="sg-panel-head">
              <span className="sg-panel-title">이벤트 로그</span>
              <div className="sg-panel-actions">
                <button className="sg-text-button" style={{ padding:"2px 6px", fontSize:fs(9) }} onClick={()=>setLogsByZone(prev=>{const next={...prev,[_zoneKey]:[]};try{localStorage.setItem("sg-logs",JSON.stringify(next))}catch{};return next})}>초기화</button>
                <button
                  className="sg-sidebar-toggle"
                  onClick={() => toggleSidebarSection("logs")}
                  aria-expanded={sidebarExpanded.logs}
                >
                  {sidebarExpanded.logs ? "간단히" : "자세히"}
                </button>
              </div>
            </div>
            <div style={{ flex:1, overflowY:"auto", padding:8 }}>
              {visibleLogs.map(log => {
                const lc = LOG_COLORS[log.type] || LOG_COLORS.sys
                return (
                  <div key={log.id} style={{ padding:"7px 9px", borderRadius:C.rSm, borderLeft:`2px solid ${lc.c}`, marginBottom:5, background:C.panel }}>
                    <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:2 }}>
                      <span style={{ fontSize:fs(8), fontWeight:800, letterSpacing:".07em", textTransform:"uppercase", color:lc.c }}>{lc.label}</span>
                      <span style={{ fontSize:fs(8), fontFamily:C.mono, color:C.t3 }}>{log.t}</span>
                    </div>
                    <div style={{ fontSize:fs(11), color:C.t1 }}>{log.title}</div>
                    {log.detail && <div style={{ fontSize:fs(9), color:C.t3, marginTop:2, fontFamily:C.mono, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{log.detail}</div>}
                  </div>
                )
              })}
              {logs.length === 0 && (
                <div style={{ padding:"12px 9px", color:C.t3, fontSize:fs(10) }}>표시할 이벤트가 없습니다</div>
              )}
            </div>
          </div>
        </div>

        {/* 지도 레이블 오버레이 */}
        <div style={{ position:"absolute", top:12, left:296, background:C.overlay, padding:"5px 10px", borderRadius:C.rMd, border:`1px solid ${C.bd}`, fontSize:fs(11), fontWeight:700, color:C.t1, zIndex:12, pointerEvents:"none", display:"flex", alignItems:"center", gap:6 }}>
          <Map size={13} color="var(--sg-cyan)" />현재 음성감지구역 지도
        </div>
        <div
          style={{ position:"absolute", top:44, left:296, background:C.overlay, padding:"5px 9px", borderRadius:C.rMd, border:`1px solid ${C.bd}`, fontSize:fs(10), color:C.t2, cursor:"pointer", transition:"border-color 0.2s", zIndex:12, maxWidth:"calc(50% - 300px)" }}
          onMouseOver={e => e.currentTarget.style.borderColor = C.cyan}
          onMouseOut={e => e.currentTarget.style.borderColor = C.bd}
          onClick={() => setMapInfoModal(true)}
        >
          <span style={{color:C.t1, fontWeight:700, marginRight:5}}>좌표</span>{mapCoord}<br/>
          <span style={{color:C.t1, fontWeight:700, marginRight:5}}>라벨</span>{mapAddr}
        </div>

        {/* 지도 범례 */}
        <div style={{ position:"absolute", top:102, left:296, background:C.overlay, padding:"5px 12px", borderRadius:C.rPill, border:`1px solid ${C.bd}`, zIndex:12, pointerEvents:"none", display:"flex", alignItems:"center", gap:12 }}>
          {[[C.green, C.greenBorder, "정상"], [C.amber, C.amberBorder, "경고"], [C.red, C.redBorder, "응급"]].map(([color, border, label]) => (
            <div key={label} style={{ display:"flex", alignItems:"center", gap:5 }}>
              <span style={{ width:8, height:8, borderRadius:"50%", background:color, boxShadow:`0 0 6px ${color}`, flexShrink:0 }} />
              <span style={{ fontSize:fs(9), fontWeight:700, color:C.t2 }}>{label}</span>
            </div>
          ))}
        </div>

            {/* 플로팅 팝업 오버레이 - 지도 위에 절대 배치 */}
            <div className="sg-float-overlay">

              {/* CCTV 플로팅 카드 - 좌측에서 슬라이드인 */}
              {cctvVisible && (
                <div className="sg-float-popup sg-float-popup--cctv">
                  <video src={cctvVideoSrc} autoPlay muted loop playsInline style={{ width:"100%", height:"100%", objectFit:"cover", display:"block" }} />
                  <div style={{ position:"absolute", top:8, left:8, display:"flex", alignItems:"center", gap:5, background:"rgba(2,7,17,.82)", border:`1px solid ${cctvStatus===2?"rgba(248,113,113,.5)":"rgba(251,191,36,.45)"}`, borderRadius:5, padding:"4px 8px", fontSize:10, fontWeight:800, color:cctvStatus===2?C.red:C.amber }}>
                    <span style={{ width:6, height:6, borderRadius:"50%", background:cctvStatus===2?C.red:C.amber, boxShadow:`0 0 8px ${cctvStatus===2?C.red:C.amber}` }} />CCTV
                  </div>
                  <button type="button" onClick={openCctvPopup} style={{ position:"absolute", top:8, right:50, background:"rgba(2,7,17,.86)", border:`1px solid ${C.bd}`, borderRadius:5, padding:"4px 7px", color:C.t1, cursor:"pointer", fontSize:9, fontWeight:800, fontFamily:"inherit" }}>팝업</button>
                  <button type="button" onClick={closeCctvView} style={{ position:"absolute", top:8, right:8, background:"rgba(248,113,113,.12)", border:"1px solid rgba(248,113,113,.35)", borderRadius:5, padding:"4px 7px", color:C.red, cursor:"pointer", fontSize:9, fontWeight:900, fontFamily:"inherit" }}>닫기</button>
                  <div style={{ position:"absolute", right:8, bottom:8, background:"rgba(2,7,17,.82)", border:`1px solid ${C.bd}`, borderRadius:5, padding:"3px 7px", fontSize:9, color:C.t2 }}>{cctvStatus===2?"위험 감지":"침입 감지"}</div>
                </div>
              )}

              {/* 스페이서 - 패널들을 우측하단으로 밀기 */}
              <div style={{ flex:1, minWidth:0 }} />

              {/* 감지 판단 요약 */}
              <div className="sg-float-popup sg-float-popup--decision">
                <div className="sg-panel-head">
                  <span className="sg-panel-title">감지 판단 요약</span>
                  <span className="sg-status-pill" style={{ color:STATUS_DATA[status]?.c, borderColor:STATUS_DATA[status]?.bd, background:STATUS_DATA[status]?.bg }}>{decisionBadgeText}</span>
                </div>
                <div className="sg-decision-body">
                  <div className="sg-decision-title" style={{ color:STATUS_DATA[status]?.c }}>{decisionMeta.situationName}</div>
                  <div className="sg-decision-reason">{decisionMeta.reason || "현재 분석 근거가 아직 수신되지 않았습니다"}</div>
                  <div className="sg-evidence-grid">
                    {[["BEATs", decisionMeta.beatsRawLabel || decisionMeta.beatsLabel || "—"], ["STT", sttDisplay], ["대응", decisionMeta.action || "감시 지속"]].map(([label, value]) => (
                      <div className="sg-evidence-item" key={label}><span>{label}</span><strong>{value}</strong></div>
                    ))}
                  </div>
                </div>
              </div>

              {/* 실시간 음향 분석 */}
              <div className="sg-float-popup sg-float-popup--sound">
                <div className="sg-panel-head">
                  <span className="sg-panel-title" style={{display:"inline-flex",alignItems:"center",gap:5}}><Activity size={13} />실시간 음향 분석</span>
                  <div style={{ display:"flex", alignItems:"center", gap:5 }}>
                    <span style={{ fontSize:fs(8), fontWeight:900, padding:"2px 6px", borderRadius:C.rPill, background:C.greenSoft, border:`1px solid ${C.greenBorder}`, color:C.green }}>LIVE</span>
                    <span className="sg-bottom-head-value">{beatsTs}</span>
                  </div>
                </div>
                <div className="sg-sound-summary">
                  <div>
                    <div className="sg-bottom-kicker">가장 강한 감지음</div>
                    <div className="sg-sound-dominant" style={{ color:dominantSound.color }}>
                      {dominantSoundValue > 0 ? dominantSound.label : "대기"}
                    </div>
                  </div>
                  <div className="sg-sound-dominant-value" style={{ color:dominantSound.color }}>{dominantSoundValue}%</div>
                </div>
                <div className="sg-sound-list">
                  {soundItems.map(item => {
                    const pct = Math.round(Math.max(0, Math.min(100, Number(item.value) || 0)))
                    const active = item.key === dominantSound.key && pct > 0
                    return (
                      <div className={`sg-sound-row${active ? " sg-sound-row--active" : ""}`} key={item.key} style={{"--sound-color":item.color}}>
                        <div className="sg-sound-label">{item.label}</div>
                        <div className="sg-sound-track"><div className="sg-sound-fill" style={{ width:`${pct}%` }} /></div>
                        <div className="sg-sound-value">{pct}%</div>
                      </div>
                    )
                  })}
                </div>
              </div>


            </div>
      </div>

      {/* ── 모달 영역 ── */}
      {mentPopup && (
        <div className="sg-modal-overlay">
          <div style={{ background:C.card, padding:24, borderRadius:C.rXl, border:`1px solid ${C.bd2}`, width:300, textAlign:"center" }}>
            <div style={{ fontSize:fs(16), fontWeight:800, marginBottom:20 }}>안내 멘트 설정 메뉴</div>
            <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
              <button className="sg-button-primary sg-button-primary--secondary" onClick={() => { setMentPopup(false); onGoConfig(); }}>초기 설정 (시스템 초기화)</button>
              <button className="sg-button-primary" onClick={() => { setMentPopup(false); setMentEditModal(true); }}>멘트 수정 (현재 상태 유지)</button>
              <button className="sg-text-button" style={{ marginTop:10 }} onClick={() => setMentPopup(false)}>닫기</button>
            </div>
          </div>
        </div>
      )}

      {mentEditModal && (
        <div className="sg-modal-overlay">
          <MentEditOverlay config={config} onUpdateConfig={onUpdateConfig} onClose={() => setMentEditModal(false)} wsRef={wsRef} />
        </div>
      )}

      {zoneModal && (
        <div className="sg-modal-overlay">
          <div style={{ background:C.card, padding:24, borderRadius:C.rXl, border:`1px solid ${C.bd2}`, width:420 }}>
            <div style={{ fontSize:fs(16), fontWeight:800, marginBottom:16 }}>구역 선택 및 관리</div>

            <div style={{ maxHeight:220, overflowY:"auto", marginBottom:16, border:`1px solid ${C.bd}`, borderRadius:C.rMd, padding:8 }}>
              {zones.length === 0 && (
                <div style={{ padding:"16px", textAlign:"center", color:C.t3, fontSize:fs(11) }}>등록된 구역이 없습니다</div>
              )}
              {zones.map(zone => (
                <div key={zone.id} style={{ marginBottom:4 }}>
                  {editingZoneId === zone.id ? (
                    <div style={{ background:C.cyanSoft, border:`1px solid ${C.cyanBorder}`, borderRadius:C.rMd, padding:10, display:"flex", flexDirection:"column", gap:6 }}>
                      <input className="sg-input sg-input--compact" value={editName} onChange={e=>setEditName(e.target.value)} placeholder="구역명" />
                      <input className="sg-input sg-input--compact" value={editCoord} onChange={e=>setEditCoord(e.target.value)} placeholder="좌표 예: 37.5665, 126.9780" />
                      <select className="sg-input sg-input--compact sg-input--select" value={editLabel} onChange={e=>setEditLabel(e.target.value)}>
                        {ZONE_LABELS.map(l => <option key={l} value={l}>{l}</option>)}
                      </select>
                      <div style={{ display:"flex", gap:6 }}>
                        <button className="sg-button-primary sg-button-primary--compact" style={{ flex:1 }} onClick={saveEditZone}>저장</button>
                        <button className="sg-text-button sg-text-button--bordered" style={{ fontSize:fs(11), padding:"6px 12px" }} onClick={()=>setEditingZoneId(null)}>취소</button>
                      </div>
                    </div>
                  ) : (
                    <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"8px", background: zone.id === selectedZoneId ? C.cyanSoft : C.panel, borderRadius:C.rSm, border: zone.id === selectedZoneId ? `1px solid ${C.cyanBorder}` : "1px solid transparent" }}>
                      <div style={{ cursor:"pointer", flex:1 }} onClick={() => { selectZone(zone); setZoneModal(false) }}>
                        <div style={{ fontSize:fs(12), fontWeight:800, color:C.t1 }}>{zone.name}</div>
                        <div style={{ fontSize:fs(9), color:C.t3, marginTop:2 }}>{zone.coord}</div>
                        <div style={{ fontSize:fs(9), color:C.cyan, marginTop:1, fontWeight:700 }}>{zone.label || "미분류"}</div>
                      </div>
                      <div style={{ display:"flex", gap:4 }}>
                        <button style={{ background:"none", border:"none", color:C.t2, cursor:"pointer", fontSize:fs(10) }} onClick={() => startEditZone(zone)}>수정</button>
                        <button style={{ background:"none", border:"none", color:C.red, cursor:"pointer", fontSize:fs(10) }} onClick={() => deleteZone(zone.id)}>삭제</button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
              <input className="sg-input" value={newZoneName} onChange={e => setNewZoneName(e.target.value)} placeholder="새 구역명" />
              <input
                className="sg-input"
                value={newZoneCoord}
                onChange={e => setNewZoneCoord(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") applyNewZoneLocationInput(e.target.value) }}
                placeholder="좌표만 입력 예: 37.5665, 126.9780 (Enter로 검색)"
              />
              <input
                className="sg-input"
                value={newZoneAddr}
                onChange={e => setNewZoneAddr(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") applyNewZoneLocationInput(e.target.value) }}
                placeholder="주소 또는 장소명 예: 인하대학교 (Enter로 좌표 자동입력)"
              />
              <select className="sg-input sg-input--select" value={newZoneLabel} onChange={e => setNewZoneLabel(e.target.value)}>
                {ZONE_LABELS.map(l => <option key={l} value={l}>{l}</option>)}
              </select>
              <button className="sg-button-primary" onClick={addZone}>추가</button>
            </div>

            <div style={{ textAlign:"right", marginTop:16 }}>
              <button className="sg-button-primary sg-button-primary--secondary sg-button-primary--auto" onClick={() => setZoneModal(false)}>닫기</button>
            </div>
          </div>
        </div>
      )}

      {mapInfoModal && (
        <div className="sg-modal-overlay">
          <div style={{ background:C.card, padding:24, borderRadius:C.rXl, border:`1px solid ${C.bd2}`, width:320 }}>
            <div style={{ fontSize:fs(16), fontWeight:800, marginBottom:16 }}>지도 위치 설정</div>
            <div style={{ marginBottom:12 }}>
              <label className="sg-label">GPS 좌표</label>
              <input
                className="sg-input"
                value={mapCoord}
                onChange={e => setMapCoord(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") applyCoordInput(e.target.value) }}
                placeholder="좌표만 입력 예: 37.450000, 126.650000 (Enter로 이동)"
              />
            </div>
            <div style={{ marginBottom:20 }}>
              <label className="sg-label">주소</label>
              <input
                className="sg-input"
                value={mapAddr}
                onChange={e => setMapAddr(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") applyLocationInput(e.target.value) }}
                placeholder="주소 또는 장소명 예: 인하대학교 (Enter로 좌표 자동입력)"
              />
            </div>
            <div style={{ display:"flex", gap:10 }}>
              <button
                className="sg-button-primary sg-button-primary--secondary"
                onClick={() => {
                  if (selectedZoneId) {
                    setZones(prev => prev.map(z => z.id === selectedZoneId ? { ...z, coord: mapCoord, addr: mapAddr } : z))
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

      {/* ── 알림 패널 ── */}
      {notifPanelOpen && (
        <>
          <div style={{ position:"fixed", inset:0, zIndex:149 }} onClick={() => setNotifPanelOpen(false)} />
          <div style={{ position:"fixed", top:48, right:10, width:310, maxHeight:400, background:C.card, border:`1px solid ${C.bd2}`, borderRadius:C.rXl, zIndex:150, display:"flex", flexDirection:"column", boxShadow:C.shadowLg, overflow:"hidden" }}>
            <div style={{ padding:"9px 14px", borderBottom:`1px solid ${C.bd}`, display:"flex", justifyContent:"space-between", alignItems:"center", flexShrink:0 }}>
              <span style={{ display:"inline-flex", alignItems:"center", gap:5, fontSize:fs(12), fontWeight:800, color:C.t1 }}><Bell size={14} />다른 구역 알림</span>
              <div style={{ display:"flex", gap:4 }}>
                {unreadCount > 0 && (
                  <button className="sg-text-button" style={{ fontSize:fs(10) }} onClick={() => setNotifications(prev => prev.map(n => ({...n, read:true})))}>모두 읽음</button>
                )}
                <button className="sg-text-button" style={{ fontSize:fs(11) }} onClick={() => setNotifPanelOpen(false)}>✕</button>
              </div>
            </div>
            <div style={{ overflowY:"auto", flex:1 }}>
              {visibleNotifications.length === 0 ? (
                <div style={{ padding:"28px 16px", textAlign:"center", color:C.t3, fontSize:fs(11) }}>다른 관리구역의 알림이 없습니다</div>
              ) : (
                visibleNotifications.map(n => (
                  <div
                    key={n.id}
                    style={{ padding:"10px 14px", borderBottom:`1px solid ${C.bd}`, cursor:"pointer", background: n.read ? "transparent" : C.cyanSoft, transition:"background .15s" }}
                    onClick={() => switchToZone(n)}
                    onMouseOver={e => e.currentTarget.style.background=C.panel2}
                    onMouseOut={e => e.currentTarget.style.background = n.read ? "transparent" : C.cyanSoft}
                  >
                    <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:4 }}>
                      <div style={{ display:"flex", alignItems:"center", gap:6 }}>
                        <span style={{ fontSize:fs(9), fontWeight:800, color: n.type===2 ? C.red : C.amber }}>
                          {n.kind === "emergency" ? "⚠ 응급상황" : n.kind === "warn2" ? "! 2차 경고" : "! 1차 경고"}
                        </span>
                        <span style={{ fontSize:fs(9), color:C.t3 }}>·</span>
                        <span style={{ fontSize:fs(9), color:C.t2, fontWeight:700 }}>{n.zoneName}</span>
                      </div>
                      {!n.read && <span style={{ width:6, height:6, borderRadius:"50%", background:C.cyan, display:"inline-block", flexShrink:0 }} />}
                    </div>
                    <div style={{ fontSize:fs(11), color:C.t1, marginBottom:3 }}>{n.message}</div>
                    <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                      <span style={{ fontSize:fs(9), color:C.t3, fontFamily:C.mono }}>{n.time}</span>
                      <span style={{ fontSize:fs(9), color:C.cyan }}>구역 전환 →</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}

      {/* ── 설정 모달 ── */}
      {settingsModal && (
        <div className="sg-modal-overlay" onClick={e => e.target === e.currentTarget && setSettingsModal(false)}>
          <div style={{ background:C.card, borderRadius:C.rXl, border:`1px solid ${C.bd2}`, width:360, overflow:"hidden" }}>
            <div style={{ padding:"13px 18px", borderBottom:`1px solid ${C.bd}`, background:C.sf, display:"flex", justifyContent:"space-between", alignItems:"center" }}>
              <span style={{ display:"inline-flex", alignItems:"center", gap:6, fontSize:fs(14), fontWeight:800 }}><Settings size={16} />시스템 설정</span>
              <button className="sg-text-button" onClick={() => setSettingsModal(false)}>✕</button>
            </div>
            <div style={{ padding:"18px" }}>
              <div style={{ marginBottom:16, padding:"12px 14px", background:C.panel, borderRadius:C.rLg, border:`1px solid ${C.bd}` }}>
                <div style={{ fontSize:fs(9), textTransform:"uppercase", letterSpacing:".12em", color:C.t3, fontWeight:700, marginBottom:6 }}>현재 접속 IP</div>
                <div style={{ fontSize:fs(13), fontWeight:700, fontFamily:C.mono, color:C.cyan, display:"flex", alignItems:"center", gap:8 }}>
                  <span style={{ display:"inline-block", width:7, height:7, borderRadius:C.rPill, background:C.green, flexShrink:0 }} />
                  {serverIP}
                </div>
              </div>
              <div style={{ marginBottom:16 }}>
                <div style={{ fontSize:fs(9), textTransform:"uppercase", letterSpacing:".12em", color:C.t3, fontWeight:700, marginBottom:8 }}>자가진단</div>
                <button className="sg-button-primary" style={{ opacity:selfCheckRunning ? 0.65 : 1 }} onClick={runSelfCheck} disabled={selfCheckRunning}>
                  <span style={{display:"inline-flex",alignItems:"center",gap:5}}><Search size={13} />{selfCheckRunning ? "진단 중..." : "자가진단 실행"}</span>
                </button>
                {selfCheckResult && (
                  <div style={{ marginTop:10, background:C.panel, borderRadius:C.rMd, border:`1px solid ${C.bd}`, overflow:"hidden" }}>
                    {selfCheckResult.map(item => (
                      <div key={item.label} style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"7px 12px", borderBottom:`1px solid ${C.bd}` }}>
                        <span style={{ fontSize:fs(11), color:C.t2 }}>{item.label}</span>
                        <span style={{ display:"inline-flex", alignItems:"center", gap:4, fontSize:fs(11), fontWeight:800, color: item.ok ? C.green : C.red }}>{item.ok ? <><Check size={13} />정상</> : <><X size={13} />오류</>}</span>
                      </div>
                    ))}
                    <div style={{ padding:"7px 12px", fontSize:fs(10), color:C.green, fontWeight:700 }}>모든 항목 정상</div>
                  </div>
                )}
              </div>
              <div style={{ borderTop:`1px solid ${C.bd}`, paddingTop:14 }}>
                <button className="sg-button-primary sg-button-primary--danger-ghost" onClick={() => { setSettingsModal(false); onLogout() }}>
                  로그아웃
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}

