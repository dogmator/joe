window.createJoeUsage = function createJoeUsage({
  state, $, escapeHtml, capitalize, addMessage, translate, fetcher
}) {
  const tr = (key, params) => translate ? translate(key, params) : key;
  function usageDescription(usage) {
    const tokens = usage.total_tokens ?? ((usage.input_tokens || 0) + (usage.output_tokens || 0));
    if (usage.cost_status === "estimated_deepseek_api" && typeof usage.cost_usd === "number") {
      return tr("deepseek_usage_estimate", { cost: usage.cost_usd.toFixed(6), tokens });
    }
    return tr("usage_tokens_count", { tokens });
  }
  async function loadUsage(force = false) {
    const button = $("refresh-usage");
    if (force) {
      button.disabled = true;
      button.classList.add("refreshing");
    }
    try {
      const response = await fetcher(`/api/usage${force ? "?force=1" : ""}`);
      if (!response.ok) throw new Error(tr("quotas_unavailable"));
      state.usage = await response.json();
      renderUsage();
    } finally {
      if (force) {
        button.disabled = false;
        button.classList.remove("refreshing");
      }
    }
  }

  function usageCardView(provider) {
    const kinds = {
      cli_unsupported: { badge: "usage_cli_badge", note: "usage_cli_note", icon: "terminal" },
      interactive_only: { badge: "usage_interactive_badge", note: "usage_interactive_note", icon: "interactive" },
      token_billing: { badge: "usage_token_badge", note: "usage_token_note", icon: "money" }
    };
    const kind = kinds[provider.quota_display];
    const problem = Boolean(provider.error_kind || provider.setup_required || provider.installed === false
      || (!kind && provider.available === false));
    const view = {
      problem, metered: provider.quota_display === "token_billing",
      badge: kind ? tr(kind.badge) : "", icon: kind?.icon || "",
      note: problem
        ? provider.error_message || provider.setup_required || provider.message || tr("usage_provider_unavailable")
        : kind ? tr(kind.note) : provider.message || "",
      balanceText: tr("usage_balance_unavailable")
    };
    if (view.metered) {
      const balance = provider.balance;
      const amount = balance?.amount ?? balance?.balance_usd;
      const currency = balance?.currency || "USD";
      const known = balance?.available === true && typeof amount === "number"
        && Number.isFinite(amount) && ["USD", "CNY"].includes(currency);
      if (known) {
        view.balanceText = new Intl.NumberFormat(document.documentElement?.lang || "en", {
          style: "currency", currency, minimumFractionDigits: 2,
          maximumFractionDigits: amount > 0 && amount < 0.01 ? 6 : 2
        }).format(amount);
        if (!problem && balance.is_available === false) view.note = tr("usage_balance_insufficient");
      } else if (!problem) {
        view.note = balance?.error_kind === "authentication"
          ? tr("usage_balance_auth", { status: balance.http_status || 401 })
          : balance?.error_kind === "credentials"
            ? tr("usage_balance_credentials") : tr("usage_balance_retry");
      }
    }
    return view;
  }

  function quotaIcon(name) {
    const paths = {
      terminal: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m7 9 3 3-3 3m6 0h4"/>',
      interactive: '<path d="M21 11a8 8 0 0 1-8 8H7l-4 3v-6a8 8 0 1 1 18-5Z"/><path d="M8 11h8m-8 4h5"/>',
      money: '<path d="M12 2v20m5-15H9a3 3 0 0 0 0 6h6a3 3 0 0 1 0 6H6"/>'
    };
    return paths[name] ? `<svg class="usage-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6">${paths[name]}</svg>` : "";
  }

  function renderUsage() {
    const target = $("usage");
    target.replaceChildren();
    for (const provider of state.usage) {
      const view = usageCardView(provider);
      const card = document.createElement("article");
      card.className = ["usage-card", view.problem ? "unavailable" : "",
        provider.quota_display ? "usage-card--info" : "",
        view.metered ? "usage-card--metered" : "", provider.stale ? "stale" : ""].filter(Boolean).join(" ");
      const badge = view.badge
        ? `<span class="usage-badge">${escapeHtml(view.badge)}</span>`
        : provider.plan ? `<span class="usage-plan">${escapeHtml(provider.plan)}</span>` : "";
      card.innerHTML = `<header><strong>${escapeHtml(provider.label || provider.provider)}</strong>${badge}</header>`;
      if (view.metered) {
        const balance = document.createElement("div");
        balance.className = "usage-balance";
        balance.innerHTML = `<span>${escapeHtml(tr("usage_balance_label"))}</span><strong>${escapeHtml(view.balanceText)}</strong>`;
        card.appendChild(balance);
      }
      if (!view.problem) {
        for (const window of provider.windows || []) card.appendChild(usageWindow(window));
        for (const metric of provider.metrics || []) {
          const row = document.createElement("div");
          row.className = "usage-metric";
          row.innerHTML = `<span>${escapeHtml(metric.name)}</span><strong>${escapeHtml(metric.value)}</strong>`;
          card.appendChild(row);
        }
      }
      if (view.note) {
        const message = document.createElement("p");
        message.className = "usage-note";
        message.innerHTML = `${quotaIcon(view.icon)}<span>${escapeHtml(view.note)}</span>`;
        card.appendChild(message);
      }
      target.appendChild(card);
    }
    updateCountdowns();
  }

  function usageWindow(window) {
    const row = document.createElement("div");
    row.className = "usage-window";
    const remaining = Number(window.remaining_percent);
    row.innerHTML = `
      <div class="usage-line"><span>${escapeHtml(window.name)}</span><strong>${formatPercent(remaining)} ${tr("remaining")}</strong></div>
      <div class="usage-bar"><i style="width:${Math.max(0, Math.min(100, remaining))}%"></i></div>
      <small class="countdown" data-reset="${window.resets_at || ""}"></small>`;
    return row;
  }

  function formatPercent(value) {
    return `${Number.isInteger(value) ? value : value.toFixed(1)} %`;
  }

  function updateCountdowns() {
    for (const node of document.querySelectorAll(".countdown")) {
      const reset = Number(node.dataset.reset);
      if (!reset) {
        node.textContent = tr("reset_unknown");
        continue;
      }
      const seconds = Math.max(0, reset - Date.now() / 1000);
      const days = Math.floor(seconds / 86400);
      const hours = Math.floor((seconds % 86400) / 3600);
      const minutes = Math.floor((seconds % 3600) / 60);
      node.textContent = seconds <= 0
        ? tr("reset_imminent")
        : tr("reset_in", { duration: `${days ? `${days} ${tr("day_short")} ` : ""}${hours ? `${hours} h ` : ""}${minutes} min` });
    }
  }

  function resetDescription(timestamp) {
    const reset = Number(timestamp);
    if (!reset) return tr("return_time_unknown");
    const seconds = Math.max(0, reset - Date.now() / 1000);
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remaining = seconds <= 0
      ? tr("reset_imminent").toLocaleLowerCase()
      : tr("in_duration", { duration: `${days ? `${days} ${tr("day_short")} ` : ""}${hours ? `${hours} h ` : ""}${minutes} min` });
    const date = new Date(reset * 1000).toLocaleString(document.documentElement.lang, {
      dateStyle: "short",
      timeStyle: "short"
    });
    return `${remaining} (${date})`;
  }

  function showQuotaNotice(event) {
    const bubble = addMessage(null, "", "notice", {
      labelKey: "joe_limit_reached"
    });
    const lines = [tr("usage_limit_reached", { provider: capitalize(event.provider) })];
    if (event.windows?.length) {
      for (const window of event.windows) {
        lines.push(`• ${window.name} : ${resetDescription(window.resets_at)}`);
      }
    } else {
      lines.push(`• ${event.usage_message || tr("cli_reset_unknown")}`);
    }
    if (event.alternatives?.length) {
      const choices = event.alternatives.map(item => {
        const models = item.models?.length ? ` (${item.models.join(", ")})` : "";
        return `${capitalize(item.provider)}${models}`;
      });
      lines.push(tr("automatic_fallbacks", { choices: choices.join(" → ") }));
    } else {
      lines.push(tr("no_fallback_available"));
    }
    lines.push(tr("shared_limit_warning"));
    bubble.textContent = lines.join("\n");
  }

  return {
    usageDescription,
    usageCardView,
    formatPercent,
    loadUsage,
    renderUsage,
    resetDescription,
    showQuotaNotice,
    updateCountdowns,
    usageWindow
  };
};
