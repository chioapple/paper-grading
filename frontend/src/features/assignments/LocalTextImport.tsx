import { useRef, type ChangeEvent } from "react";

const MAX_LOCAL_TEXT_BYTES = 100_000;

function readUtf8Text(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("文件读取失败"));
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.readAsText(file, "UTF-8");
  });
}

export function LocalTextImport({
  fieldLabel,
  language,
  onError,
  onText,
}: {
  fieldLabel: string;
  language: "zh" | "en";
  onError: (message: string) => void;
  onText: (value: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const buttonText = language === "zh" ? "从 .txt/.md 读取" : "Read .txt/.md";
  const inputLabel = `${buttonText}${fieldLabel}`;

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    const extension = file.name.toLowerCase().match(/\.[^.]+$/)?.[0];
    if (extension !== ".txt" && extension !== ".md") {
      onError(language === "zh" ? "只支持 .txt 或 .md 文件。" : "Only .txt or .md files are supported.");
      return;
    }
    if (file.size > MAX_LOCAL_TEXT_BYTES) {
      onError(language === "zh" ? "文件不能超过 100KB。" : "The file must not exceed 100KB.");
      return;
    }
    try {
      const content = await readUtf8Text(file);
      if (!content.trim() || content.includes("\uFFFD")) {
        throw new Error("invalid UTF-8");
      }
      onError("");
      onText(content);
    } catch {
      onError(language === "zh" ? "文件必须是有效的 UTF-8 文本。" : "The file must be valid UTF-8 text.");
    }
  }

  return (
    <div className="local-text-import">
      <input
        ref={inputRef}
        accept=".txt,.md,text/plain,text/markdown"
        aria-label={inputLabel}
        className="visually-hidden"
        onChange={handleFile}
        type="file"
      />
      <button className="secondary-button local-text-import__button" onClick={() => inputRef.current?.click()} type="button">
        {buttonText}
      </button>
      <small>
        {language === "zh"
          ? "文件只在当前浏览器读取，不会上传原文件。"
          : "The file is read only in this browser and is not uploaded."}
      </small>
    </div>
  );
}
