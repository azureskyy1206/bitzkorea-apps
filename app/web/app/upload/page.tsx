"use client";
import Link from "next/link";
import { useState } from "react";
import { postFormData } from "../../lib/api";
import { useRouter } from "next/navigation";

export default function UploadPage() {
 const [file, setFile] = useState<File | null>(null);
 const [status, setStatus] = useState<"idle"|"uploading"|"done"|"error">("idle");
 const [result, setResult] = useState<any>(null);
 const router = useRouter();

 async function submit() {
 if (!file) return;
 setStatus("uploading");
 try {
 const fd = new FormData();
 fd.append("file", file);
 const r = await postFormData<any>("/api/upload", fd);
 setResult(r);
 setStatus("done");
 } catch (e: any) {
 setResult({ error: String(e) });
 setStatus("error");
 }
 }

 return (
 <div className="space-y-6">
 <div className="text-sm text-slate-500">
 <Link href="/sales/changes" className="text-blue-600 hover:underline">
 ← 영업변동사항
 </Link>
 </div>
 <h1 className="text-2xl font-bold">엑셀 업로드</h1>

 <div
 className="border-2 border-dashed border-slate-300 rounded p-12 text-center bg-white"
 onDragOver={(e) => e.preventDefault()}
 onDrop={(e) => {
 e.preventDefault();
 const f = e.dataTransfer.files?.[0];
 if (f) setFile(f);
 }}
 >
 {file ? (
 <p className="text-lg">{file.name} <span className="text-slate-500">({(file.size/1024/1024).toFixed(2)} MB)</span></p>
 ) : (
 <p className="text-slate-500">파일을 여기에 끌어다 놓거나 아래 버튼으로 선택</p>
 )}
 <input
 type="file"
 accept=".xlsx"
 onChange={(e) => setFile(e.target.files?.[0] || null)}
 className="mt-4"
 />
 </div>

 <div className="flex gap-3">
 <button
 disabled={!file || status === "uploading"}
 onClick={submit}
 className="bg-blue-600 text-white px-6 py-2 rounded hover:bg-blue-700 disabled:bg-slate-300"
 >
 {status === "uploading" ? "업로드 중..." : "업로드 + 자동 변동사항"}
 </button>
 {result && status === "done" && (
 <button
 onClick={() => router.push(`/report/${result.business_date}`)}
 className="bg-green-600 text-white px-6 py-2 rounded hover:bg-green-700"
 >
 리포트 보기 →
 </button>
 )}
 </div>

 {result && (
 <pre className="bg-slate-900 text-green-300 p-4 rounded text-xs overflow-auto">
 {JSON.stringify(result, null, 2)}
 </pre>
 )}
 </div>
 );
}
