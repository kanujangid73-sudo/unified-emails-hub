import { useMemo, useRef, useState } from "react";
import { emailDocument, sanitizeEmail } from "../lib/sanitize.js";
import Icon from "./Icon.jsx";

// Shows an HTML email inside a sandboxed iframe (see lib/sanitize.js for why).
// "allow-same-origin" without "allow-scripts" lets the app measure the content height while
// still stopping all script execution in the frame.
export default function EmailFrame({ html }) {
  const [allowImages, setAllowImages] = useState(false);
  const [height, setHeight] = useState(120);
  const frame = useRef(null);

  const { doc, blockedImages, trackingPixels } = useMemo(() => {
    const result = sanitizeEmail(html, { allowImages });
    return { ...result, doc: emailDocument(result.html, { allowImages }) };
  }, [html, allowImages]);

  const fit = () => {
    const body = frame.current?.contentDocument?.documentElement;
    if (body) setHeight(body.scrollHeight + 4);
  };

  return (
    <div className="email-frame">
      {(blockedImages > 0 || trackingPixels > 0) && (
        <div className="privacy-note">
          <Icon name="shield" size={16} />
          <span>
            {trackingPixels > 0 && `Blocked ${trackingPixels} tracking pixel${trackingPixels > 1 ? "s" : ""}. `}
            {blockedImages > 0 && !allowImages && `${blockedImages} remote image${blockedImages > 1 ? "s" : ""} hidden to protect your privacy.`}
          </span>
          {blockedImages > 0 && !allowImages && (
            <button className="link" onClick={() => setAllowImages(true)}>
              Show images
            </button>
          )}
        </div>
      )}
      <iframe
        ref={frame}
        title="Email content"
        sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
        srcDoc={doc}
        onLoad={fit}
        style={{ height }}
      />
    </div>
  );
}
