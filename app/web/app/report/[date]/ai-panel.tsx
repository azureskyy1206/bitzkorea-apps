"use client";
import { useState } from "react";
import { API_BASE } from "../../../lib/api";

type Msg = { role: "user" | "ai"; text: string; latency?: number };

export default function AiPanel({ date, totals, rowCount }: any) {
 const [open, setOpen] = useState(false);
 const [loading, setLoading] = useState(false);
 const [summary, setSummary] = useState<string>("");
 const [summaryLatency, setSummaryLatency] = useState<number | null>(null);
 const [question, setQuestion] = useState("");
 const [chat, setChat] = useState<Msg[]>([]);

 async function fetchSummary() {
 setLoading(true);
 setSummary("");
 try {
 const r = await fetch(`${API_BASE}/api/ai/summary?date=${date}`);
 const j = await r.json();
 if (j.detail) {
 setSummary(`에러: ${j.detail}`);
 } else {
 setSummary(j.answer);
 setSummaryLatency(j.latency_ms);
 }
 } catch (e: any) {
 setSummary(`에러: ${e}`);
 } finally {
 setLoading(false);
 }
 }

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
 body: JSON.stringify({ question: q, date_hint: date }),
 });
 const j = await r.json();
 setChat(c => [...c, { role: "ai", text: j.answer || j.detail || "응답 없음", latency: j.latency_ms }]);
 } catch (e: any) {
 setChat(c => [...c, { role: "ai", text: `에러: ${e}` }]);
 } finally {
 setLoading(false);
 }
 }

 return (
 <div className="bg-white rounded shadow">
 <button
 onClick={() => { setOpen(!open); if (!open && !summary) fetchSummary(); }}
 className="w-full p-3 text-left flex justify-between items-center hover:bg-slate-50"
 >
 <span className="font-semibold"> AI 분석</span>
 <span className="text-slate-400">{open ? "▲" : "▼"}</span>
 </button>

 {open && (
 <div className="p-4 border-t space-y-4">
 {/* 자동 요약 */}
 <div>
 <div className="flex items-center justify-between mb-2">
 <h3 className="text-sm font-semibold text-slate-700"> 자동 요약</h3>
 <button
 onClick={fetchSummary}
 disabled={loading}
 className="text-xs px-3 py-1 bg-slate-200 rounded hover:bg-slate-300"
 >다시 생성</button>
 </div>
 {loading && !summary && (
 <p className="text-slate-500 text-sm">생성 중... (첫 호출은 30초~2분)</p>
 )}
 {summary && (
 <div className="bg-slate-50 p-3 rounded">
 <pre className="whitespace-pre-wrap text-sm font-sans">{summary}</pre>
 {summaryLatency && (
 <div className="text-xs text-slate-400 mt-2">{(summaryLatency/1000).toFixed(1)}초</div>
 )}
 </div>
 )}
 </div>

 {/* 채팅 */}
 <div>
 <h3 className="text-sm font-semibold text-slate-700 mb-2"> 자연어 질의</h3>
 <div className="space-y-2 mb-2 max-h-80 overflow-y-auto">
 {chat.length === 0 && (
 <p className="text-xs text-slate-400">
 예: "강주형 담당 변경 알려줘", "오늘 가장 큰 이익 변동", "Loss 발생한 건"
 </p>
 )}
 {chat.map((m, i) => (
 <div key={i} className={`p-2 rounded text-sm ${m.role === "user" ? "bg-blue-100 ml-12" : "bg-slate-100 mr-12"}`}>
 <div className="text-xs text-slate-500 mb-1">
 {m.role === "user" ? "나" : "AI"}
 {m.latency && ` · ${(m.latency/1000).toFixed(1)}초`}
 </div>
 <pre className="whitespace-pre-wrap font-sans">{m.text}</pre>
 </div>
 ))}
 {loading && chat.length > 0 && (
 <div className="text-slate-400 text-xs">AI 응답 생성 중...</div>
 )}
 </div>
 <div className="flex gap-2">
 <input
 value={question}
 onChange={e => setQuestion(e.target.value)}
 onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) ask(); }}
 placeholder="질문 입력 후 Enter"
 disabled={loading}
 className="flex-1 border rounded px-3 py-2 text-sm"
 />
 <button
 onClick={ask}
 disabled={loading || !question.trim()}
 className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:bg-slate-300"
 >
 전송
 </button>
 </div>
 </div>
 </div>
 )}
 </div>
 );
}
