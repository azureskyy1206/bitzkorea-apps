import HelpShell from "@/components/help/HelpShell";
import { ADOBE_ADMIN_HELP_TREE, ADOBE_HELP_VERSION } from "@/lib/help/adobe-tree";
import { ADOBE_ADMIN_TOPICS } from "@/lib/help/adobe-topics";
import { attachScreenshotsToTopics } from "@/lib/help/screenshot-figure";

export default function AdminHelpPage({ params }: { params: { slug?: string[] } }) {
  const slug = params.slug?.length ? params.slug.join("/") : "start";
  const topics = attachScreenshotsToTopics(ADOBE_ADMIN_TOPICS, "help/screenshots/admin");

  return (
    <HelpShell
      productName="Adobe 포털 관리자"
      version={ADOBE_HELP_VERSION}
      basePath="/admin/help"
      homeHref="/admin"
      tree={ADOBE_ADMIN_HELP_TREE}
      topics={topics}
      slug={slug}
      isAdmin
    />
  );
}
