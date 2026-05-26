(function () {
  const modal = document.getElementById("submitModal");
  const submitBtn = document.getElementById("submitBtn");

  function setupReveal() {
    const nodes = document.querySelectorAll(".reveal");
    if (!("IntersectionObserver" in window)) {
      nodes.forEach((node) => node.classList.add("in"));
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("in");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });

    nodes.forEach((node) => observer.observe(node));
  }

  function setupVotes() {
    document.addEventListener("click", (event) => {
      const button = event.target.closest(".vote-btn");
      if (!button) return;

      event.preventDefault();
      event.stopPropagation();

      const wrap = button.closest(".votes");
      const upBtn = wrap.querySelector(".vote-up");
      const downBtn = wrap.querySelector(".vote-down");
      const upCount = upBtn.querySelector(".vote-count");
      const downCount = downBtn.querySelector(".vote-count");
      const isUp = button.classList.contains("vote-up");
      const state = wrap.dataset.state;
      let up = parseInt(upCount.textContent.replace(/,/g, ""), 10);
      let down = parseInt(downCount.textContent.replace(/,/g, ""), 10);

      if (state === "up") up -= 1;
      if (state === "down") down -= 1;

      upBtn.classList.remove("is-active");
      downBtn.classList.remove("is-active");

      if (isUp) {
        if (state === "up") {
          wrap.dataset.state = "none";
        } else {
          up += 1;
          wrap.dataset.state = "up";
          upBtn.classList.add("is-active");
        }
      } else if (state === "down") {
        wrap.dataset.state = "none";
      } else {
        down += 1;
        wrap.dataset.state = "down";
        downBtn.classList.add("is-active");
      }

      upCount.textContent = up.toLocaleString();
      downCount.textContent = down.toLocaleString();
    });
  }

  function setupTabs() {
    const tabs = document.querySelectorAll(".tab");
    const panels = document.querySelectorAll(".tab-panel");
    if (!tabs.length) return;

    function activateTab(tab) {
      const name = tab.dataset.tab;
      tabs.forEach((item) => item.classList.toggle("active", item === tab));
      panels.forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.panel === name);
      });
    }

    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        activateTab(tab);
        const targetId = tab.dataset.scrollTarget;
        if (!targetId) return;
        const target = document.getElementById(targetId);
        if (!target) return;
        requestAnimationFrame(() => {
          target.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      });
    });
  }

  function setupCopyButtons() {
    document.querySelectorAll(".copy-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const text = btn.getAttribute("data-copy") || "";
        try {
          await navigator.clipboard.writeText(text);
        } catch (_error) {
          const ta = document.createElement("textarea");
          ta.value = text;
          document.body.appendChild(ta);
          ta.select();
          try {
            document.execCommand("copy");
          } catch (_execError) {}
          document.body.removeChild(ta);
        }
        const original = btn.textContent;
        btn.textContent = "Copied!";
        btn.classList.add("copied");
        setTimeout(() => {
          btn.textContent = original;
          btn.classList.remove("copied");
        }, 1400);
      });
    });
  }

  function setupDiscussions() {
    document.querySelectorAll(".disc-up").forEach((button) => {
      button.addEventListener("click", () => {
        const score = button.parentElement.querySelector(".disc-score");
        let value = parseInt(score.textContent.replace(/,/g, ""), 10);
        if (button.classList.toggle("is-active")) value += 1;
        else value -= 1;
        score.textContent = value.toLocaleString();
      });
    });

    const postButton = document.querySelector(".disc-post");
    if (!postButton) return;

    postButton.addEventListener("click", () => {
      const textarea = document.querySelector(".disc-composer textarea");
      const text = (textarea.value || "").trim();
      if (!text) {
        textarea.focus();
        return;
      }

      const list = document.querySelector(".disc-list");
      const thread = document.createElement("div");
      thread.className = "disc-thread";
      thread.innerHTML = `
        <div class="disc-vote">
          <button type="button" class="disc-up is-active" aria-label="Upvote">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 15-6-6-6 6"/></svg>
          </button>
          <span class="disc-score">1</span>
        </div>
        <div class="disc-body">
          <div class="disc-meta"><span class="disc-author">you</span> · just now</div>
          <div class="disc-text"></div>
          <div class="disc-foot"><button type="button" class="disc-action">Reply</button><span class="disc-replies">No replies yet</span></div>
        </div>`;

      thread.querySelector(".disc-text").textContent = text;
      list.prepend(thread);
      textarea.value = "";

      thread.querySelector(".disc-up").addEventListener("click", function () {
        const score = this.parentElement.querySelector(".disc-score");
        let value = parseInt(score.textContent.replace(/,/g, ""), 10);
        if (this.classList.toggle("is-active")) value += 1;
        else value -= 1;
        score.textContent = value.toLocaleString();
      });

      const count = document.querySelector(".disc-count");
      if (count) {
        const current = parseInt(count.textContent, 10) || 0;
        count.textContent = `${current + 1} threads`;
      }
    });
  }

  function setupModal() {
    if (!modal || !submitBtn) return;

    function openModal() {
      modal.classList.add("open");
      modal.setAttribute("aria-hidden", "false");
    }

    function closeModal() {
      modal.classList.remove("open");
      modal.setAttribute("aria-hidden", "true");
    }

    submitBtn.addEventListener("click", openModal);
    document.getElementById("modalClose")?.addEventListener("click", closeModal);
    modal.addEventListener("click", (event) => {
      if (event.target === modal) closeModal();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && modal.classList.contains("open")) closeModal();
    });
  }

  function setupPackageBuilder() {
    const builder = document.getElementById("packageBuilder");
    const addBtn = document.getElementById("addPackageBtn");
    if (!builder || !addBtn) return;

    addBtn.addEventListener("click", () => {
      const row = document.createElement("div");
      row.className = "package-row";
      row.innerHTML = `
        <input name="package_name" type="text" placeholder="Pro" />
        <input name="package_price" type="text" placeholder="$49/mo" />
        <input name="package_description" type="text" placeholder="For growing teams" />
      `;
      builder.appendChild(row);
    });
  }

  setupReveal();
  setupVotes();
  setupTabs();
  setupCopyButtons();
  setupDiscussions();
  setupModal();
  setupPackageBuilder();
})();
