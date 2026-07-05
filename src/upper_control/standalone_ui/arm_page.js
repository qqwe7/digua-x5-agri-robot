(function () {
  let armRefreshTimer = null;

  function byId(id) {
    return document.getElementById(id);
  }

  function setText(id, value) {
    const el = byId(id);
    if (el) el.textContent = value;
  }

  function setI18nText(key, value) {
    document.querySelectorAll(`[data-i18n="${key}"]`).forEach((el) => {
      el.textContent = value;
    });
  }

  function fmtNumber(value) {
    const num = Number(value);
    return Number.isFinite(num) ? num.toFixed(2) : "--";
  }

  function fmtTime(value) {
    if (!value) return "--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString("zh-CN", { hour12: false });
  }

  function armConnected(snapshot) {
    return Boolean(snapshot?.device_link?.connected) && Boolean(snapshot?.arm?.connected);
  }

  function jointEntries(snapshot) {
    const joints = snapshot?.arm?.joints;
    if (!joints || typeof joints !== "object") return [];
    return Object.entries(joints)
      .map(([key, value]) => [Number(key), value])
      .filter(([key]) => Number.isFinite(key))
      .sort((a, b) => a[0] - b[0]);
  }

  function updateFlowStatus(snapshot) {
    const savedPoints = snapshot?.arm?.saved_points || {};
    const homeReady = Boolean(savedPoints.reset_home);
    const pickReady = Boolean(savedPoints.save1);
    const basketReady = Boolean(savedPoints.save2);

    const bindState = (id, ready) => {
      const el = byId(id);
      if (!el) return;
      el.textContent = ready ? "已设置" : "未设置";
      el.classList.toggle("ready", ready);
    };

    bindState("armFlowHomeState", homeReady);
    bindState("armFlowPickState", pickReady);
    bindState("armFlowBasketState", basketReady);

    const finishBtn = byId("armCtrlFinishFlowBtn");
    const summary = byId("armFlowSummary");
    const ready = homeReady && pickReady && basketReady;
    if (finishBtn) finishBtn.disabled = !ready;
    if (summary) {
      summary.textContent = ready
        ? "复位点、夹取点、放篮点都已设置完成，可以开始按流程作业。"
        : "请先完成复位点、夹取点、放篮点设置。";
    }
  }

  function renderStaticFrame() {
    const camera = byId("armCameraView");
    if (camera) {
      camera.innerHTML = `
        <div class="arm-camera-placeholder">
          <b>相机标注画面</b>
          <span>当前区域用于展示目标框、识别标签、候选抓取区域以及机械臂实时位置。</span>
        </div>
      `;
    }

    setI18nText("tabArm", "视觉抓取监看");
    setI18nText("armTeachTitle", "视觉抓取状态总览");
    setI18nText("armTeachDesc", "左侧显示相机标注画面，右侧显示机械臂当前位置、关节状态与抓取流程。该页面仅用于展示和监看。");
    setI18nText("armReadonlyTag", "只读监看");
    setI18nText("armVisionPanel", "相机标注画面");
    setI18nText("armPosePanel", "机械臂实时状态");
    setI18nText("armJointPanel", "关节状态");
    setI18nText("armWorkflow", "抓取流程状态");
    setI18nText("armProtocolTitle", "视觉 / 机械臂事件日志");
    setI18nText("armMonitorTitle", "监看说明");
    setI18nText("armMonitorLine1", "相机标注区用于展示目标识别画面与抓取流程状态。");
    setI18nText("armMonitorLine2", "右侧状态区用于显示机械臂当前位置、关节信息与最近一次任务状态。");
    setI18nText("armMonitorLine3", "控制操作放在单独的小面板中，不在本页主界面公开显示。");
    setText("armSecretEntryBtn", "机械臂实时状态显示");
    setText("armCtrlResult", "等待隐藏控制台命令...");
    setText("pageTitle", "视觉抓取监看");
  }

  function renderArmSnapshot(snapshot) {
    const connected = armConnected(snapshot);
    const arm = snapshot?.arm || {};
    const joints = jointEntries(snapshot);
    const lastCommand = snapshot?.last_command || {};
    const linkSource = snapshot?.device_link?.source || "--";
    const lastSeen = fmtTime(snapshot?.device_link?.last_seen);
    const transportMode = arm.transport_mode || "--";
    const port = arm.port || "--";
    const baudrate = arm.baudrate || 0;
    const readyText = arm.ready ? "ready" : connected ? "idle" : "offline";
    const zeroText = arm.logical_zero_active ? "已启用" : "未启用";

    const visionMeta = byId("armVisionMeta");
    if (visionMeta) {
      visionMeta.innerHTML = `
        <div class="arm-meta-row"><b>目标类别</b><span>${snapshot?.vision?.target_class || "--"}</span></div>
        <div class="arm-meta-row"><b>识别置信度</b><span>${fmtNumber(snapshot?.vision?.confidence)}</span></div>
        <div class="arm-meta-row"><b>机械臂链路</b><span>${connected ? "已连接" : "未连接"} / ${linkSource}</span></div>
        <div class="arm-meta-row"><b>最近心跳</b><span>${lastSeen}</span></div>
        <div class="arm-meta-row"><b>传输模式</b><span>${transportMode}</span></div>
      `;
    }

    const pose = byId("armPoseGrid");
    if (pose) {
      pose.innerHTML = `
        <div class="arm-pose-item"><b>机械臂状态</b><span>${readyText}</span></div>
        <div class="arm-pose-item"><b>连接参数</b><span>${port} / ${baudrate || "--"}</span></div>
        <div class="arm-pose-item"><b>逻辑零位</b><span>${zeroText}</span></div>
      `;
    }

    const jointsBox = byId("armJointGrid");
    if (jointsBox) {
      jointsBox.innerHTML = joints.length
        ? joints
            .map(
              ([index, value]) =>
                `<div class="arm-joint-item"><b>关节 ${index}</b><span>${fmtNumber(value)}°</span></div>`
            )
            .join("")
        : `<div class="arm-joint-item"><b>关节状态</b><span>等待地瓜派X5上报</span></div>`;
    }

    const flow = byId("armFlowList");
    if (flow) {
      flow.innerHTML = `
        <div class="arm-flow-item"><b>1. 上位机链路</b><span>${connected ? "已连通" : "等待连接"}</span></div>
        <div class="arm-flow-item"><b>2. 当前模式</b><span>${snapshot?.system?.mode || "--"}</span></div>
        <div class="arm-flow-item"><b>3. 最近命令</b><span>${lastCommand.intent || "--"}</span></div>
        <div class="arm-flow-item"><b>4. 命令结果</b><span>${lastCommand.result || "--"}</span></div>
      `;
    }

    const logs = byId("armResult");
    if (logs) {
      const jointSummary = joints.length
        ? joints.map(([index, value]) => `J${index}=${fmtNumber(value)}`).join(" ")
        : "尚未收到关节数据";
      logs.textContent = [
        `机械臂链路 -> ${connected ? "已连接" : "未连接"}`,
        `最近命令 -> ${lastCommand.intent || "-"} / ${lastCommand.result || "-"}`,
        `说明 -> ${lastCommand.message || "-"}`,
        `关节反馈 -> ${jointSummary}`,
      ].join("\n");
    }

    const resultBox = byId("armCtrlResult");
    if (resultBox && !resultBox.dataset.busy) {
      resultBox.textContent = [
        `链路: ${connected ? "已连接" : "未连接"}`,
        `模式: ${transportMode}`,
        `最近结果: ${lastCommand.message || "等待隐藏控制台命令..."}`,
      ].join("\n");
    }
    updateFlowStatus(snapshot);
  }

  async function refreshArmSnapshot() {
    if (typeof window.apiFetch !== "function") return;
    try {
      const snapshot = await window.apiFetch("/api/state");
      renderArmSnapshot(snapshot);
    } catch (error) {
      const resultBox = byId("armCtrlResult");
      if (resultBox && !resultBox.dataset.busy) {
        resultBox.textContent = `机械臂状态刷新失败\n${error.message || error}`;
      }
    }
  }

  function patchUnsupportedJog() {
    document.querySelectorAll('.arm-jog-btn[data-joint="7"]').forEach((button) => {
      button.disabled = true;
      button.title = "当前地瓜派X5机械臂服务仅接入 1-6 轴，夹爪未接通";
    });
    document.querySelectorAll(".arm-jog-item").forEach((item) => {
      if (!item.querySelector('.arm-jog-btn[data-joint="7"]')) return;
      const head = item.querySelector(".arm-jog-head span");
      if (head) head.textContent = "夹爪（未接入）";
    });
  }

  function restoreGripperJog() {
    document.querySelectorAll('.arm-jog-btn[data-joint="7"]').forEach((button) => {
      button.disabled = false;
      button.removeAttribute("title");
    });
    document.querySelectorAll(".arm-jog-item").forEach((item) => {
      if (!item.querySelector('.arm-jog-btn[data-joint="7"]')) return;
      const head = item.querySelector(".arm-jog-head span");
      if (head) head.textContent = "夹爪 ID7";
    });
  }

  function openSecretPanel(open) {
    byId("armSecretMask")?.classList.toggle("hidden", !open);
    byId("armSecretPanel")?.classList.toggle("hidden", !open);
    byId("armSecretPanel")?.setAttribute("aria-hidden", open ? "false" : "true");
  }

  async function sendArmCommand(intent, params) {
    const resultBox = byId("armCtrlResult");
    if (resultBox) {
      resultBox.dataset.busy = "1";
      resultBox.textContent = "正在发送机械臂命令...";
    }

    if (typeof window.apiFetch !== "function") {
      if (resultBox) {
        delete resultBox.dataset.busy;
        resultBox.textContent = "页面接口未就绪，请刷新后重试。";
      }
      return;
    }

    try {
      const result = await window.apiFetch("/api/command", {
        method: "POST",
        body: JSON.stringify({
          source: "web_arm_hidden_console",
          intent,
          params: params || {}
        })
      });

      if (resultBox) {
        resultBox.textContent = [
          `命令: ${result.intent || intent}`,
          `结果: ${result.result || "-"}`,
          `说明: ${result.message || "-"}`,
        ].join("\n");
      }
      await refreshArmSnapshot();
    } catch (error) {
      if (resultBox) resultBox.textContent = `机械臂命令失败\n${error.message || error}`;
    } finally {
      if (resultBox) delete resultBox.dataset.busy;
    }
  }

  function bindSecretConsole() {
    byId("armSecretEntryBtn")?.addEventListener("click", () => openSecretPanel(true));
    byId("armSecretMask")?.addEventListener("click", () => openSecretPanel(false));

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") openSecretPanel(false);
    });

    byId("armCtrlConnectBtn")?.addEventListener("click", () => sendArmCommand("arm_connect", {}));
    byId("armCtrlReadBtn")?.addEventListener("click", () => sendArmCommand("arm_read_positions", {}));
    byId("armCtrlSaveHomeBtn")?.addEventListener("click", () => sendArmCommand("arm_save_reset_home", {}));
    byId("armCtrlGotoHomeBtn")?.addEventListener("click", () => sendArmCommand("arm_goto_reset_home", {}));
    byId("armCtrlSaveHomeBtn2")?.addEventListener("click", () => sendArmCommand("arm_save_reset_home", {}));
    byId("armCtrlGotoHomeBtn2")?.addEventListener("click", () => sendArmCommand("arm_goto_reset_home", {}));
    byId("armCtrlStopBtn")?.addEventListener("click", () => sendArmCommand("arm_stop", {}));

    byId("armCtrlSavePickBtn")?.addEventListener("click", () => {
      sendArmCommand("arm_save_target", { slot: 1 });
    });

    byId("armCtrlGotoPickBtn")?.addEventListener("click", () => {
      sendArmCommand("arm_goto_target", { slot: 1 });
    });

    byId("armCtrlSaveBasketBtn")?.addEventListener("click", () => {
      sendArmCommand("arm_save_target", { slot: 2 });
    });

    byId("armCtrlGotoBasketBtn")?.addEventListener("click", () => {
      sendArmCommand("arm_goto_target", { slot: 2 });
    });

    byId("armCtrlFinishFlowBtn")?.addEventListener("click", () => {
      const resultBox = byId("armCtrlResult");
      if (resultBox) {
        resultBox.textContent = [
          "一套流程已完成设置：",
          "1. 复位点已设置",
          "2. 夹取点已设置",
          "3. 放篮点已设置",
          "后续可按“回到复位点 -> 回到夹取点 -> 回到放篮点 -> 回到复位点”执行。"
        ].join("\n");
      }
    });

    document.querySelectorAll(".arm-jog-btn").forEach((button) => {
      button.addEventListener("click", () => {
        const joint = Number(button.getAttribute("data-joint") || 1);
        const direction = button.getAttribute("data-direction") || "pos";
        const delta = Number(byId("armCtrlDeltaInput")?.value || 5);
        sendArmCommand("arm_jog_joint", {
          joint,
          delta_deg: direction === "neg" ? -delta : delta
        });
      });
    });
  }

  function patchTabTitle() {
    if (typeof window.showTab !== "function" || window.__armMonitorPatched) return;
    const original = window.showTab;
    window.showTab = function patched(tab) {
      original(tab);
      if (tab === "arm") {
        setText("pageTitle", "视觉抓取监看");
      }
    };
    window.__armMonitorPatched = true;
  }

  function init() {
    renderStaticFrame();
    patchUnsupportedJog();
    restoreGripperJog();
    bindSecretConsole();
    patchTabTitle();
    openSecretPanel(false);
    void refreshArmSnapshot();
    clearInterval(armRefreshTimer);
    armRefreshTimer = window.setInterval(() => {
      void refreshArmSnapshot();
    }, 2000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.addEventListener("load", init);
})();
