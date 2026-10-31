export default function SiteFooter() {
  return (
    <footer className="mt-6 border-t border-slate-200 pb-4 pt-8">
      <div className="flex flex-wrap justify-between gap-6">
        <div className="space-y-2">
          <p className="text-sm leading-6 text-slate-500">
            보이스피싱 예방을 위한 모의훈련 서비스
          </p>
        </div>
        <nav
          aria-label="하단 메뉴"
          className="flex gap-5 text-sm text-slate-500"
        >
          <a href="/" className="hover:text-slate-900">
            서비스 소개
          </a>
          <a href="/apply" className="hover:text-slate-900">
            훈련 신청
          </a>
          <a href="/lookup" className="hover:text-slate-900">
            신청 조회
          </a>
          <a href="/control" className="hover:text-slate-900">
            login
          </a>
        </nav>
      </div>
      <div className="mt-6 flex flex-wrap justify-between gap-2 border-t border-slate-100 pt-4 text-xs text-slate-400">
        <p>© {new Date().getFullYear()} VoiceVaccine All rights reserved.</p>
        <p>사전 동의 기반 모의훈련</p>
      </div>
    </footer>
  );
}
