interface AuditLogPayload {
    project_id: string;
    repository_name: string;
    target_language: "python" | "javascript";
    execution_status: string;
    execution_summary: string;
    created_at: string;
    pull_request_number?: number;
    suggestion_posted?: boolean;
}

class DashboardTelemetryController {
    private apiEndpoint: string = "/api/v1/logs-stream/";
    private gridElement: HTMLElement | null;
    private statusFilter: HTMLSelectElement | null;
    private logsData: AuditLogPayload[] = [];
    private pollInterval: number | null = null;

    constructor() {
        this.gridElement = document.getElementById("logs-grid");
        this.statusFilter = document.getElementById("status-filter") as HTMLSelectElement | null;
    }

    public initialize(): void {
        if (this.statusFilter) {
            this.statusFilter.addEventListener("change", () => this.renderLogs());
        }
        this.fetchLogs();
        this.pollInterval = window.setInterval(() => this.fetchLogs(), 5000);
    }

    public async refresh(): Promise<void> {
        if (!this.gridElement) return;
        this.gridElement.innerHTML = `<div class="col-span-full text-center py-12 text-theme-secondary"><p class="text-sm">Refreshing...</p></div>`;
        await this.fetchLogs();
    }

    private normalizeDisplayStatus(status: string): string {
        const successVariants = ["SUCCESS", "AUTONOMOUS_FIX_COMMENTED", "COMPLETED"];
        const pendingVariants = ["PENDING", "QUEUED", "RUNNING"];
        if (successVariants.includes(status)) return "SUCCESS";
        if (pendingVariants.includes(status)) return "PENDING";
        return "FAILED";
    }

    private async fetchLogs(): Promise<void> {
        try {
            const response = await fetch(this.apiEndpoint);
            if (!response.ok) throw new Error("Network error");
            this.logsData = await response.json();
            this.renderLogs();
        } catch (error) {
            if (!this.gridElement) return;
            this.gridElement.innerHTML = `<div class="col-span-full text-center py-12 text-theme-secondary border border-dashed border-theme rounded-xl">
                <p class="text-sm">Failed to load logs: ${(error as Error).message}</p></div>`;
        }
    }

    private renderLogs(): void {
        if (!this.gridElement) return;

        const filter = this.statusFilter ? this.statusFilter.value : "all";
        const filtered = filter === "all"
            ? this.logsData
            : this.logsData.filter(l => this.normalizeDisplayStatus(l.execution_status) === filter);

        if (filtered.length === 0) {
            this.gridElement.innerHTML = `<div class="col-span-full text-center py-16 text-theme-secondary border border-dashed border-theme rounded-xl">
                <p class="text-sm font-medium">No execution logs match the current filter.</p></div>`;
            return;
        }

        this.gridElement.innerHTML = "";
        for (const log of filtered) {
            this.gridElement.appendChild(this.createCard(log));
        }
    }

    private createCard(log: AuditLogPayload): HTMLElement {
        const card = document.createElement("div");
        const displayStatus = this.normalizeDisplayStatus(log.execution_status);

        const isSuccess = displayStatus === "SUCCESS";
        const isPending = displayStatus === "PENDING";

        const statusColor = isSuccess
            ? "bg-emerald-500/10 text-emerald-400 ring-emerald-500/20"
            : isPending
                ? "bg-amber-500/10 text-amber-400 ring-amber-500/20 animate-pulse"
                : "bg-rose-500/10 text-rose-400 ring-rose-500/20";

        const langColor = (log.target_language || "python") === "python"
            ? "bg-sky-500/10 text-sky-400 ring-sky-500/20"
            : "bg-amber-500/10 text-amber-400 ring-amber-500/20";

        const prLink = log.pull_request_number && log.pull_request_number > 0
            ? `<a href="https://github.com/${log.repository_name}/pull/${log.pull_request_number}" target="_blank" class="inline-flex items-center gap-1 text-xs text-brand-400 hover:text-brand-300 transition-colors">
                <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                PR #${log.pull_request_number}
            </a>`
            : `<span class="text-xs text-theme-secondary">CLI / Direct</span>`;

        const suggestionBadge = log.suggestion_posted
            ? `<span class="inline-flex items-center gap-1 rounded-full bg-brand-500/10 px-2 py-0.5 text-[10px] font-medium text-brand-400 ring-1 ring-brand-500/20">
                <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                Suggestion Posted
            </span>`
            : "";

        const summary = log.execution_summary || "No summary available.";

        card.className = "flex flex-col justify-between rounded-xl border border-theme bg-theme-card p-5 card-hover";
        card.innerHTML = `
            <div>
                <div class="flex items-center justify-between gap-3">
                    <div class="min-w-0 flex-1">
                        <h3 class="text-sm font-semibold truncate text-theme-primary" title="${log.repository_name}">${log.repository_name}</h3>
                    </div>
                    <span class="shrink-0 rounded-full px-2.5 py-1 text-[10px] font-medium ring-1 ring-inset ${statusColor}">${log.execution_status}</span>
                </div>
                <div class="mt-2 flex items-center flex-wrap gap-x-3 gap-y-1 text-xs text-theme-secondary">
                    <span class="font-mono text-[10px]">${log.project_id}</span>
                    <span>•</span>
                    <span class="rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ring-1 ring-inset ${langColor}">${log.target_language || "python"}</span>
                    <span>•</span>
                    ${prLink}
                </div>
                <div class="terminal-wrapper mt-3 rounded-lg bg-theme-primary/50 p-3 border border-theme cursor-pointer">
                    <p class="font-mono text-xs text-theme-secondary leading-relaxed line-clamp-3 overflow-hidden whitespace-pre-wrap terminal-summary">${summary}</p>
                    <button class="terminal-toggle mt-1 text-[10px] text-brand-400 hover:text-brand-300">Show more</button>
                </div>
            </div>
            <div class="mt-4 pt-3 border-t border-theme flex items-center justify-between">
                <div class="flex items-center gap-2">${suggestionBadge}</div>
                <span class="text-[11px] text-theme-secondary font-mono">${new Date(log.created_at).toLocaleString()}</span>
            </div>
        `;

        const terminalBlock = card.querySelector(".terminal-wrapper") as HTMLElement;
        const summaryEl = terminalBlock.querySelector(".terminal-summary") as HTMLElement;
        const toggleBtn = terminalBlock.querySelector(".terminal-toggle") as HTMLButtonElement;

        const needsToggle = summary.length > 150;
        if (!needsToggle) {
            toggleBtn.style.display = "none";
            summaryEl.classList.remove("line-clamp-3");
        }

        let expanded = false;
        toggleBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            expanded = !expanded;
            summaryEl.classList.toggle("line-clamp-3", !expanded);
            toggleBtn.textContent = expanded ? "Show less" : "Show more";
        });

        return card;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const controller = new DashboardTelemetryController();
    controller.initialize();
    (window as any).__dashboardController = controller;
});
