import type { Config } from "tailwindcss";

/** 금액·날짜·수량 등: 맑은 고딕 우선(프로젝트 전역에서 font-mono로 숫자 표시에 사용) */
const malgunNumericStack = [
  '"Malgun Gothic"',
  '"맑은 고딕"',
  '"Apple SD Gothic Neo"',
  '"Noto Sans KR"',
  "ui-monospace",
  "SFMono-Regular",
  "Consolas",
  "monospace",
] as const;

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        mono: [...malgunNumericStack],
      },
    },
  },
  plugins: [],
};
export default config;
