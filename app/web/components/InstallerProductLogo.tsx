import Image from "next/image";

/** 설치 파일 카드용 공식 브랜드 로고 (/public/installer-logos) */

const LOGOS: Record<
  string,
  { src: string; alt: string; boxClass: string; imgClass: string }
> = {
  office: {
    src: "/installer-logos/microsoft-office.svg",
    alt: "Microsoft Office",
    boxClass: "relative h-12 w-12 shrink-0 overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-black/5",
    imgClass: "object-contain p-1",
  },
  windows: {
    src: "/installer-logos/microsoft-windows.svg",
    alt: "Microsoft Windows",
    boxClass: "relative h-12 w-12 shrink-0 overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-black/5",
    imgClass: "object-contain p-1",
  },
  hangul: {
    src: "/installer-logos/hancom-hangul.png",
    alt: "한글",
    boxClass: "relative h-12 w-12 shrink-0 overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-black/5",
    imgClass: "object-contain p-0.5",
  },
  hancom_office: {
    src: "/installer-logos/hancom-office.png",
    alt: "한컴오피스",
    boxClass: "relative h-12 w-12 shrink-0 overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-black/5",
    imgClass: "object-contain p-0.5",
  },
};

type Props = { productKey: string; className?: string };

export default function InstallerProductLogo({ productKey, className }: Props) {
  const logo = LOGOS[productKey];
  const box = className ?? logo?.boxClass;

  if (!logo) {
    return (
      <span
        className={`${box ?? ""} flex h-12 w-12 items-center justify-center rounded-xl bg-slate-200 text-sm font-semibold text-slate-600`}
        aria-hidden
      >
        ?
      </span>
    );
  }

  return (
    <span className={box}>
      <Image src={logo.src} alt={logo.alt} fill className={logo.imgClass} sizes="128px" unoptimized />
    </span>
  );
}
