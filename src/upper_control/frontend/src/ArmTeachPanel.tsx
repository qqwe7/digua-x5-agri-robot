import { Alert, Button, Card, Col, Divider, InputNumber, Row, Select, Space, Table, Tag, Typography, message } from "antd";
import { useMemo, useState } from "react";

import { sendCommand } from "./api";
import type { CommandResponse } from "./types";

const { Paragraph, Text, Title } = Typography;

const jointOptions = [
  { label: "Joint 1", value: 1 },
  { label: "Joint 2", value: 2 },
  { label: "Joint 3", value: 3 },
  { label: "Joint 4", value: 4 },
  { label: "Joint 5", value: 5 },
  { label: "Joint 6", value: 6 },
  { label: "Gripper (Joint 7)", value: 7 }
];

const slotOptions = [
  { label: "Target 1", value: 1 },
  { label: "Target 2", value: 2 },
  { label: "Target 3", value: 3 },
  { label: "Target 4", value: 4 }
];

const quickActions = [
  {
    title: "Connect Arm",
    intent: "arm_connect",
    params: {},
    description: "Connect upper computer to RDK_X5 arm service."
  },
  {
    title: "Read Positions",
    intent: "arm_read_positions",
    params: {},
    description: "Read the current angle of joints 1 through 7."
  },
  {
    title: "Save Reset Home",
    intent: "arm_save_reset_home",
    params: {},
    description: "Capture the current posture as reset_home."
  },
  {
    title: "Go Reset Home",
    intent: "arm_goto_reset_home",
    params: {},
    description: "Replay the stored reset_home posture."
  },
  {
    title: "Stop Arm",
    intent: "arm_stop",
    params: {},
    danger: true,
    description: "Stop current arm motion immediately."
  }
];

const protocolRows = [
  { key: "connect", intent: "arm_connect", params: "{} or { host, port }", note: "Connect to the board-side arm service." },
  { key: "read", intent: "arm_read_positions", params: "{}", note: "Return 7-joint position snapshot." },
  { key: "save-home", intent: "arm_save_reset_home", params: "{}", note: "Save current posture as reset_home." },
  { key: "goto-home", intent: "arm_goto_reset_home", params: "{}", note: "Move back to reset_home." },
  { key: "save-target", intent: "arm_save_target", params: "{ slot: 1..4 }", note: "Save current posture into a teach slot." },
  { key: "goto-target", intent: "arm_goto_target", params: "{ slot: 1..4 }", note: "Replay a teach slot." },
  { key: "jog", intent: "arm_jog_joint", params: "{ joint: 1..7, delta_deg: number }", note: "Jog a joint by relative degrees." },
  { key: "stop", intent: "arm_stop", params: "{}", note: "Emergency stop for arm motion." }
];

type Props = {
  onCommandComplete?: (response: CommandResponse) => Promise<void> | void;
};

export function ArmTeachPanel({ onCommandComplete }: Props) {
  const [joint, setJoint] = useState<number>(5);
  const [deltaDeg, setDeltaDeg] = useState<number>(5);
  const [slot, setSlot] = useState<number>(1);
  const [commandLoading, setCommandLoading] = useState<string>("");
  const [lastResponse, setLastResponse] = useState<CommandResponse | null>(null);

  const protocolColumns = useMemo(
    () => [
      { title: "Intent", dataIndex: "intent", key: "intent", width: 180 },
      { title: "Params", dataIndex: "params", key: "params", width: 220 },
      { title: "Meaning", dataIndex: "note", key: "note" }
    ],
    []
  );

  async function runCommand(intent: string, params: Record<string, unknown>) {
    setCommandLoading(intent);
    try {
      const response = await sendCommand({ source: "web_arm_teach", intent, params });
      setLastResponse(response);
      if (response.allowed) {
        message.success(`${intent}: ${response.message}`);
      } else {
        message.warning(`${intent}: ${response.message}`);
      }
      await onCommandComplete?.(response);
    } catch (error) {
      const reason = error instanceof Error ? error.message : "arm command failed";
      message.error(reason);
    } finally {
      setCommandLoading("");
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message="Mechanical arm teach workflow"
        description="This page sends standard arm teach intents through the existing /api/command channel. The board-side service only needs to map these intents to your RDK_X5 arm controller."
      />

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={14}>
          <Card title="Teach Actions">
            <Space direction="vertical" size={16} style={{ width: "100%" }}>
              <Row gutter={[12, 12]}>
                {quickActions.map((action) => (
                  <Col xs={24} md={12} key={action.intent}>
                    <Card size="small" className="arm-action-card">
                      <Space direction="vertical" size={8} style={{ width: "100%" }}>
                        <Text strong>{action.title}</Text>
                        <Text type="secondary">{action.description}</Text>
                        <Button
                          type={action.danger ? "primary" : "default"}
                          danger={action.danger}
                          loading={commandLoading === action.intent}
                          onClick={() => void runCommand(action.intent, action.params)}
                        >
                          Send
                        </Button>
                      </Space>
                    </Card>
                  </Col>
                ))}
              </Row>

              <Divider style={{ margin: 0 }} />

              <Card size="small" title="Teach Slot">
                <Space wrap>
                  <Select style={{ width: 180 }} options={slotOptions} value={slot} onChange={setSlot} />
                  <Button loading={commandLoading === "arm_save_target"} onClick={() => void runCommand("arm_save_target", { slot })}>
                    Save Target
                  </Button>
                  <Button type="primary" loading={commandLoading === "arm_goto_target"} onClick={() => void runCommand("arm_goto_target", { slot })}>
                    Replay Target
                  </Button>
                </Space>
              </Card>

              <Card size="small" title="Joint Jog">
                <Space wrap>
                  <Select style={{ width: 220 }} options={jointOptions} value={joint} onChange={setJoint} />
                  <InputNumber
                    min={0.1}
                    max={180}
                    step={0.5}
                    value={deltaDeg}
                    onChange={(value) => setDeltaDeg(Number(value ?? 5))}
                    addonAfter="deg"
                  />
                  <Button loading={commandLoading === "arm_jog_joint_pos"} onClick={() => void runCommand("arm_jog_joint", { joint, delta_deg: Number(deltaDeg) })}>
                    Positive Jog
                  </Button>
                  <Button loading={commandLoading === "arm_jog_joint_neg"} onClick={() => void runCommand("arm_jog_joint", { joint, delta_deg: -Number(deltaDeg) })}>
                    Negative Jog
                  </Button>
                </Space>
                <Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
                  The current RDK_X5 arm service exposes joints 1 through 7, with the gripper mapped to CAN ID 7.
                </Paragraph>
              </Card>
            </Space>
          </Card>
        </Col>

        <Col xs={24} xl={10}>
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <Card title="Command Feedback">
              {lastResponse ? (
                <Space direction="vertical" size={8}>
                  <Text>
                    Status: {lastResponse.allowed ? <Tag color="green">allowed</Tag> : <Tag color="red">blocked</Tag>}
                  </Text>
                  <Text>Intent: {lastResponse.intent}</Text>
                  <Text>Result: {lastResponse.result}</Text>
                  <Paragraph style={{ marginBottom: 0 }}>Message: {lastResponse.message}</Paragraph>
                </Space>
              ) : (
                <Text type="secondary">No arm command has been sent yet.</Text>
              )}
            </Card>

            <Card title="Workflow Suggestion">
              <Space direction="vertical" size={6}>
                <Text>1. Connect Arm</Text>
                <Text>2. Read Positions</Text>
                <Text>3. Save Reset Home</Text>
                <Text>4. Jog joints to target posture</Text>
                <Text>5. Save Target</Text>
                <Text>6. Go Reset Home</Text>
                <Text>7. Replay Target</Text>
              </Space>
            </Card>
          </Space>
        </Col>
      </Row>

      <Card title="Arm Teach Protocol">
        <Table rowKey="key" columns={protocolColumns} dataSource={protocolRows} pagination={false} scroll={{ x: 760 }} />
      </Card>
    </Space>
  );
}
