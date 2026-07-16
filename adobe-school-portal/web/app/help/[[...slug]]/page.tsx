import HelpShell from "@/components/help/HelpShell";
import { ADOBE_SCHOOL_HELP_TREE, ADOBE_HELP_VERSION } from "@/lib/help/adobe-tree";
import { ADOBE_SCHOOL_TOPICS } from "@/lib/help/adobe-topics";
import { attachScreenshotsToTopics } from "@/lib/help/screenshot-figure";

export default function SchoolHelpPage({ params }: { params: { slug?: string[] } }) {
  const slug = params.slug?.length ? params.slug.join("/") : "start";
  const topics = attachScreenshotsToTopics(ADOBE_SCHOOL_TOPICS, "help/screenshots/school");

  return (
    <HelpShell
      productName="Adobe 학교 포털"
      version={ADOBE_HELP_VERSION}
      basePath="/help"
      homeHref="/login"
      tree={ADOBE_SCHOOL_HELP_TREE}
      topics={topics}
      slug={slug}
      isAdmin={false}
    />
  );
}
