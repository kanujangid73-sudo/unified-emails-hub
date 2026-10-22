import { useEffect, useRef } from "react";
import Icon from "./Icon.jsx";

// A modal dialog: closes on Escape or a click outside, and keeps focus inside while open.
export default function Dialog({ title, onClose, children, wide = false }) {
  const panel = useRef(null);

  useEffect(() => {
    const previous = document.activeElement;
    panel.current?.querySelector("input, textarea, select, button:not(.dialog-close)")?.focus();
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
      if (e.key === "Tab" && panel.current) {
        const items = [...panel.current.querySelectorAll("button, input, textarea, select, a[href]")].filter((el) => !el.disabled);
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      previous?.focus?.();
    };
  }, [onClose]);

  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <section ref={panel} className={`dialog ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <header className="dialog-head">
          <h2>{title}</h2>
          <button className="icon-btn dialog-close" onClick={onClose} aria-label="Close">
            <Icon name="close" />
          </button>
        </header>
        <div className="dialog-body">{children}</div>
      </section>
    </div>
  );
}
