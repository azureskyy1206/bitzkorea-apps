import fs from "fs";
import path from "path";
import type { HelpTopic } from "./types";

/** 서버에서 스크린샷 파일 존재 시 figure 블록을 주제 맨 앞에 삽입 */
export function attachScreenshotToTopic(
  slug: string,
  topic: HelpTopic,
  screenshotDir: string,
): HelpTopic {
  const fileName = `${slug.replace(/\//g, "__")}.png`;
  const diskPath = path.join(process.cwd(), "public", screenshotDir, fileName);
  if (!fs.existsSync(diskPath)) return topic;

  const figure = {
    type: "figure" as const,
    src: `/${screenshotDir}/${fileName}`,
    alt: topic.title,
    caption: "실제 포털 화면 캡처입니다.",
  };

  const blocks = topic.blocks.filter((b) => b.type !== "ui");
  return { ...topic, blocks: [figure, ...blocks] };
}

export function attachScreenshotsToTopics(
  topics: Record<string, HelpTopic>,
  screenshotDir: string,
): Record<string, HelpTopic> {
  const out: Record<string, HelpTopic> = {};
  for (const [slug, topic] of Object.entries(topics)) {
    out[slug] = attachScreenshotToTopic(slug, topic, screenshotDir);
  }
  return out;
}
