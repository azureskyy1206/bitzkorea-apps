import Link from "next/link";
import type { HelpBlock } from "@/lib/help/types";
import HelpUiExample from "./HelpUiExample";

export default function HelpTopicBody({ blocks }: { blocks: HelpBlock[] }) {
  return (
    <article className="help-prose">
      {blocks.map((b, i) => {
        switch (b.type) {
          case "p":
            return (
              <p key={i} className="help-p">
                {b.text}
              </p>
            );
          case "h2":
            return (
              <h2 key={i} className="help-h2">
                {b.text}
              </h2>
            );
          case "h3":
            return (
              <h3 key={i} className="help-h3">
                {b.text}
              </h3>
            );
          case "ul":
            return (
              <ul key={i} className="help-ul">
                {b.items.map((item, j) => (
                  <li key={j}>{item}</li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={i} className="help-ol">
                {b.items.map((item, j) => (
                  <li key={j}>{item}</li>
                ))}
              </ol>
            );
          case "table":
            return (
              <div key={i} className="help-table-wrap">
                <table className="help-table">
                  <thead>
                    <tr>
                      {b.headers.map((h, j) => (
                        <th key={j}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((row, ri) => (
                      <tr key={ri}>
                        {row.map((cell, ci) => (
                          <td key={ci}>{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "tip":
            return (
              <div key={i} className="help-tip">
                {b.title ? <strong>{b.title}</strong> : null}
                <p>{b.text}</p>
              </div>
            );
          case "caution":
            return (
              <div key={i} className="help-caution">
                {b.title ? <strong>{b.title}</strong> : null}
                <p>{b.text}</p>
              </div>
            );
          case "links":
            return (
              <ul key={i} className="help-link-list">
                {b.items.map((l, j) => (
                  <li key={j}>
                    {l.external ? (
                      <a href={l.href} target="_blank" rel="noopener noreferrer">
                        {l.label}
                      </a>
                    ) : (
                      <Link href={l.href}>{l.label}</Link>
                    )}
                  </li>
                ))}
              </ul>
            );
          case "figure":
            return (
              <figure key={i} className="help-figure">
                <div className="help-figure-label">화면 캡처</div>
                <div className="help-figure-img-wrap">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={b.src} alt={b.alt} className="help-figure-img" loading="lazy" />
                </div>
                {b.caption ? <figcaption className="help-ui-caption">{b.caption}</figcaption> : null}
              </figure>
            );
          case "ui":
            return (
              <HelpUiExample
                key={i}
                variant={b.variant}
                caption={b.caption}
                callouts={b.callouts}
              />
            );
          default:
            return null;
        }
      })}
    </article>
  );
}
