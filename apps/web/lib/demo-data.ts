import demoIssuesJson from "../../../packages/shared/demo-data/issues.json";
import type { DemoCycle, DemoIssue, DemoProject } from "@/types/demo";

export const demoIssues = demoIssuesJson as DemoIssue[];

export const demoProjects: DemoProject[] = [
  {
    id: "PRJ-101",
    name: "Jira Migration",
    description: "Import active epics, issues, labels, and project history.",
    progress: 74,
    status: "Active",
    lead: "Avery Brooks",
    team: "Platform",
    targetDate: "2026-09-28"
  },
  {
    id: "PRJ-102",
    name: "Sprint Planning Refresh",
    description: "Simplify cycle setup and planning review for managers.",
    progress: 58,
    status: "Active",
    lead: "Maya Chen",
    team: "Product Engineering",
    targetDate: "2026-10-12"
  },
  {
    id: "PRJ-103",
    name: "Bug Triage Workflow",
    description: "Reduce duplicate reports and speed up ownership assignment.",
    progress: 42,
    status: "At risk",
    lead: "Noah Patel",
    team: "Product Engineering",
    targetDate: "2026-09-18"
  }
];

export const demoCycle: DemoCycle = {
  id: "CYC-14",
  name: "Frontend Cycle 14",
  daysLeft: 8,
  progress: 68,
  completed: 18,
  inProgress: 9,
  remaining: 11,
  focus: ["Bug triage", "Cycle planning", "GitHub sync", "Assignment flow"],
  status: "Active",
  team: "Product Engineering",
  startDate: "2026-08-24",
  endDate: "2026-09-08"
};

export const demoTeam = [
  {
    name: "Maya Chen",
    initials: "MC",
    role: "Frontend Lead",
    load: 84
  },
  {
    name: "Noah Patel",
    initials: "NP",
    role: "Product Engineer",
    load: 71
  },
  {
    name: "Avery Brooks",
    initials: "AB",
    role: "Engineering Manager",
    load: 63
  },
  {
    name: "Iris Morgan",
    initials: "IM",
    role: "Platform Engineer",
    load: 77
  }
];

export const integrations = [
  {
    name: "GitHub",
    description: "Sync pull requests, commits, and issue references.",
    connected: true
  },
  {
    name: "Slack",
    description: "Create issues from messages and receive project updates.",
    connected: true
  },
  {
    name: "Jira Import",
    description: "Bring active Jira projects into a simplified workspace.",
    connected: true
  },
  {
    name: "Sentry",
    description: "Create bug reports from production exceptions.",
    connected: false
  }
];
