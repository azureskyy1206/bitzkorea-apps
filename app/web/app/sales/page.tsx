import Link from "next/link";

export default function SalesHome() {
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold sm:text-2xl">영업</h1>

      <div className="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2">
        <Link href="/sales/quote" className="block min-h-[4.5rem] rounded bg-white p-4 shadow hover:bg-slate-50 sm:p-5">
          <div className="font-semibold">견적서 생성</div>
          <div className="text-sm text-slate-500 mt-1">
            V2 화면으로 견적서를 생성/다운로드합니다.
          </div>
        </Link>

        <Link href="/sales/quotes" className="block min-h-[4.5rem] rounded bg-white p-4 shadow hover:bg-slate-50 sm:p-5">
          <div className="font-semibold">견적서 리스트</div>
          <div className="text-sm text-slate-500 mt-1">
            팀 전체 견적서를 확인·다운로드·발주 요청합니다. (일반 사용자 대시보드는 본인 담당 견적만)
          </div>
        </Link>

        <Link href="/sales/customers" className="block min-h-[4.5rem] rounded bg-white p-4 shadow hover:bg-slate-50 sm:p-5">
          <div className="font-semibold">고객 조회</div>
          <div className="text-sm text-slate-500 mt-1">견적서에서 추출된 고객 DB를 검색/조회합니다.</div>
        </Link>

        <Link href="/sales/pricebook" className="block min-h-[4.5rem] rounded bg-white p-4 shadow hover:bg-slate-50 sm:p-5">
          <div className="font-semibold">가격표</div>
          <div className="text-sm text-slate-500 mt-1">
            주문(영업) 품목과 DB 가격표를 맞추고, 단가를 입력·저장·제품을 추가합니다.
          </div>
        </Link>

        <Link href="/sales/pricebook/upload" className="block min-h-[4.5rem] rounded bg-white p-4 shadow hover:bg-slate-50 sm:p-5">
          <div className="font-semibold">가격표 업로드</div>
          <div className="text-sm text-slate-500 mt-1">벤더별 가격표 파일을 업로드해 일괄 반영합니다.</div>
        </Link>

        <Link href="/sales/installer-links" className="block min-h-[4.5rem] rounded bg-white p-4 shadow hover:bg-slate-50 sm:p-5">
          <div className="font-semibold">설치 파일 다운로드</div>
          <div className="text-sm text-slate-500 mt-1">
            Microsoft·한글 벤더별 OneDrive 공유 링크를 등록하고 다운로드합니다.
          </div>
        </Link>
      </div>
    </div>
  );
}

