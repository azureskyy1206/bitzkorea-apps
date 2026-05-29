"use client";
import { useState, useRef, useEffect } from "react";
import { API_BASE } from "../../lib/api";

type Msg = { role: "user" | "ai"; text: string; latency?: number; intent?: any; rows?: any[] };

export default function ChatPage() {
 const [question, setQuestion] = useState("");
 const [dateHint, setDateHint] = useState<string>("");
 const [chat, setChat] = useState<Msg[]>([]);
 const [loading, setLoading] = useState(false);
 const [showRows, setShowRows] = useState<number | null>(null);
 const endRef = useRef<HTMLDivElement>(null);

 useEffect(() => {
 endRef.current?.scrollIntoView({ behavior: "smooth" });
 }, [chat, loading]);

 async function ask() {
 if (!question.trim()) return;
 const q = question;
 setQuestion("");
 setChat(c => [...c, { role: "user", text: q }]);
 setLoading(true);
 try {
 const r = await fetch(`${API_BASE}/api/ai/ask`, {
 method: "POST",
 headers: { "Content-Type": "application/json" },
 body: JSON.stringify({
 question: q,
 date_hint: dateHint || undefined
 }),
 });
 const j = await r.json();
 setChat(c => [...c, {
 role: "ai",
 text: j.answer || j.detail || "응답 없음",
 latency: j.latency_ms,
 intent: j.intent,
 rows: j.rows,
 }]);
 } catch (e: any) {
 setChat(c => [...c, { role: "ai", text: `에러: ${e}` }]);
 } finally {
 setLoading(false);
 }
 }

 function clear() {
 setChat([]);
 setShowRows(null);
 }

 const examples = [
 "2026-04-20 변경 요약해줘",
 "강주형 담당 변경 알려줘",
 "오늘 가장 큰 이익 변동",
 "Loss 발생한 건",
 "매출월 연기된 건",
 ];

 return (
 <div className="space-y-4">
 <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
 <h1 className="text-xl font-bold sm:text-2xl"> AI 채팅</h1>
 <button
 onClick={clear}
 disabled={chat.length === 0}
 className="text-sm bg-slate-200 px-3 py-1 rounded hover:bg-slate-300 disabled:opacity-50"
 >
 대화 초기화
 </button>
 </div>

 {/* 날짜 컨텍스트 */}
 <div className="flex flex-col gap-3 rounded bg-white p-3 text-sm shadow sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
 <label className="font-semibold shrink-0">기준 날짜 (선택):</label>
 <input
 type="date"
 value={dateHint}
 onChange={e => setDateHint(e.target.value)}
 className="w-full min-w-0 rounded border px-2 py-2 sm:w-auto sm:py-1"
 />
 <span className="text-slate-500 text-xs">
 비워두면 질문에서 날짜를 추출합니다 (예: "4월 20일")
 </span>
 </div>

 {/* 채팅 영역 */}
 <div className="bg-white rounded shadow min-h-[400px] flex flex-col">
 <div className="flex-1 p-4 space-y-3 overflow-y-auto max-h-[600px]">
 {chat.length === 0 && (
 <div className="text-center py-12 text-slate-400">
 <p className="mb-3 text-sm">예시 질문을 클릭해 시작하세요</p>
 <div className="flex flex-wrap gap-2 justify-center">
 {examples.map((ex, i) => (
 <button
 key={i}
 onClick={() => setQuestion(ex)}
 className="text-xs bg-slate-100 hover:bg-slate-200 px-3 py-1.5 rounded border"
 >
 {ex}
 </button>
 ))}
 </div>
 </div>
 )}
 {chat.map((m, i) => (
 <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
 <div className={`max-w-[min(100%,36rem)] p-3 rounded-lg sm:max-w-[80%] ${
 m.role === "user" ? "bg-blue-500 text-white" : "bg-slate-100"
 }`}>
 <div className={`text-xs mb-1 ${m.role === "user" ? "text-blue-100" : "text-slate-500"}`}>
 {m.role === "user" ? "나" : "AI"}
 {m.latency && ` · ${(m.latency/1000).toFixed(1)}초`}
 {m.intent?.template && (
 <span className="ml-2 px-1.5 py-0.5 bg-white/20 rounded text-xs">
 {m.intent.template}
 </span>
 )}
 </div>
 <pre className="whitespace-pre-wrap font-sans text-sm">{m.text}</pre>
 {m.rows && m.rows.length > 0 && (
 <button
 onClick={() => setShowRows(showRows === i ? null : i)}
 className="mt-2 text-xs underline opacity-70 hover:opacity-100"
 >
 {showRows === i ? "근거 데이터 숨기기" : `근거 데이터 ${m.rows.length}건 보기`}
 </button>
 )}
 {showRows === i && m.rows && (
 <pre className="mt-2 text-xs bg-white/50 p-2 rounded overflow-auto max-h-60">
 {JSON.stringify(m.rows, null, 2)}
 </pre>
 )}
 </div>
 </div>
 ))}
 {loading && (
 <div className="flex justify-start">
 <div className="bg-slate-100 p-3 rounded-lg text-sm text-slate-500">
 AI 응답 생성 중...
 </div>
 </div>
 )}
 <div ref={endRef} />
 </div>

 {/* 입력 */}
 <div className="border-t p-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-2">
 <input
 value={question}
 onChange={e => setQuestion(e.target.value)}
 onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }}
 placeholder="질문 입력 후 Enter (예: 강주형 담당 4월 20일 변경)"
 disabled={loading}
 className="min-w-0 flex-1 rounded border px-3 py-2.5 text-sm sm:py-2"
 />
 <button
 onClick={ask}
 disabled={loading || !question.trim()}
 className="w-full shrink-0 rounded bg-blue-600 px-6 py-2.5 text-white hover:bg-blue-700 disabled:bg-slate-300 sm:w-auto sm:py-2"
 >
 전송
 </button>
 </div>
 </div>

 <div className="text-xs text-slate-500">
 답변은 데이터베이스 SQL 결과 기반으로 생성됩니다. 숫자가 의심되면 "근거 데이터 보기"로 원본 확인하세요.
 </div>
 </div>
 );
}
