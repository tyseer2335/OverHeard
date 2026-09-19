"use client";

export default function BrowserPreview({ url }: { url: string }) {
  return (
    <div className="card overflow-hidden p-0">
      <div className="flex items-center gap-2 border-b border-line px-4 py-2 text-xs text-slate-400">
        <span className="h-2.5 w-2.5 rounded-full bg-rose-500/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-amber-500/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/70" />
        <span className="ml-2">Browserbase — live collection</span>
        <a href={url} target="_blank" rel="noreferrer" className="ml-auto text-indigo-400 hover:text-indigo-300">
          open ↗
        </a>
      </div>
      <iframe src={url} title="Browserbase live view" className="h-72 w-full bg-white" sandbox="allow-scripts allow-same-origin" />
    </div>
  );
}
