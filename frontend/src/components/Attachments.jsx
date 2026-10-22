import { useRef, useState } from "react";
import { MAX_ATTACHMENT_BYTES, downloadAttachment, fileKind, formatSize, toUpload } from "../lib/files.js";
import Icon from "./Icon.jsx";

const KIND_LABEL = { image: "IMG", pdf: "PDF", sheet: "XLS", archive: "ZIP", file: "FILE" };

// Files attached to a received or sent message, each downloadable.
export function AttachmentList({ attachments, token, onError }) {
  const [busy, setBusy] = useState(null);
  const files = attachments.filter((a) => !a.inline);
  if (!files.length) return null;

  const download = async (attachment) => {
    setBusy(attachment.id);
    try {
      await downloadAttachment(token, attachment);
    } catch (err) {
      onError(err.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <ul className="attachments" aria-label="Attachments">
      {files.map((a) => {
        const kind = fileKind(a.mime_type, a.filename);
        return (
          <li key={a.id}>
            <button className="attachment" onClick={() => download(a)} disabled={busy === a.id} title={`Download ${a.filename}`}>
              <span className={`file-badge ${kind}`}>{KIND_LABEL[kind]}</span>
              <span className="attachment-name">{a.filename}</span>
              <span className="muted small">{busy === a.id ? "Downloading…" : formatSize(a.size)}</span>
              <Icon name="download" size={16} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}

// "Attach files" for compose and reply: keeps the chosen files and their total size in check.
export function FilePicker({ files, onChange, onError }) {
  const input = useRef(null);
  const total = files.reduce((sum, f) => sum + f.size, 0);

  const add = async (chosen) => {
    const next = [...files];
    let size = total;
    for (const file of chosen) {
      if (size + file.size > MAX_ATTACHMENT_BYTES) {
        onError(`Attachments can be at most ${formatSize(MAX_ATTACHMENT_BYTES)} in total; ${file.name} was left out.`);
        continue;
      }
      try {
        next.push({ ...(await toUpload(file)), size: file.size, key: `${file.name}-${file.size}-${file.lastModified}-${Math.random()}` });
        size += file.size;
      } catch (err) {
        onError(err.message);
      }
    }
    onChange(next);
  };

  return (
    <div className="file-picker">
      <button type="button" className="btn ghost small" onClick={() => input.current?.click()}>
        <Icon name="attach" size={16} /> Attach files
      </button>
      <input
        ref={input}
        type="file"
        multiple
        hidden
        onChange={(e) => {
          add([...e.target.files]);
          e.target.value = "";
        }}
      />
      {files.length > 0 && (
        <ul className="chosen-files">
          {files.map((f) => (
            <li key={f.key}>
              <span className="attachment-name">{f.filename}</span>
              <span className="muted small">{formatSize(f.size)}</span>
              <button type="button" className="icon-btn tiny" onClick={() => onChange(files.filter((x) => x.key !== f.key))} aria-label={`Remove ${f.filename}`}>
                <Icon name="close" size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// What the send API expects: no local-only fields.
export function forUpload(files) {
  return files.map(({ filename, mime_type, data }) => ({ filename, mime_type, data }));
}
