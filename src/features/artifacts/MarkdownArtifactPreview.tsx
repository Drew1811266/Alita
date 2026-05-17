import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

type MarkdownArtifactPreviewProps = {
  content: string;
};

export function MarkdownArtifactPreview({
  content,
}: MarkdownArtifactPreviewProps) {
  return (
    <div className="artifactPreviewMarkdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
