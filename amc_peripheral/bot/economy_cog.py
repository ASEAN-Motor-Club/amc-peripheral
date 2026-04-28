"""Economy management cog — SubsidyRule CRUD and JobPostingConfig for the LLM agent."""

import json
import logging
from datetime import UTC, datetime

import discord
from discord.ext import commands

from amc_peripheral.settings import (
    BACKEND_API_URL,
    ECONOMY_AUDIT_CHANNEL_ID,
    FINANCIAL_MINISTER_ROLE_ID,
)

log = logging.getLogger(__name__)

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "manage_subsidy_rules_list",
            "description": "List all government subsidy rules for cargo deliveries, including inactive rules. Returns full detail: name, reward type/value, priority, cargo/area requirements, budget allocation and spending.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_subsidy_rule_create",
            "description": "Create a new government subsidy rule for cargo deliveries. Use get_current_subsidies first to understand existing rules and avoid duplicates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Descriptive name for the rule (e.g. 'Long-haul bonus for steel deliveries')",
                    },
                    "reward_type": {
                        "type": "string",
                        "enum": ["PERCENTAGE", "FLAT"],
                        "description": "PERCENTAGE = multiplier on base payment (e.g. 3.0 = 300%), FLAT = fixed amount added",
                    },
                    "reward_value": {
                        "type": "number",
                        "description": "The reward value (must be positive). For PERCENTAGE: 3.0 means 300%. For FLAT: absolute amount.",
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Evaluation order (higher = checked first). Default 0.",
                    },
                    "active": {
                        "type": "boolean",
                        "description": "Whether the rule is active. Default true.",
                    },
                    "scales_with_damage": {
                        "type": "boolean",
                        "description": "If true, reward is multiplied by vehicle health percentage. Default false.",
                    },
                    "requires_on_time": {
                        "type": "boolean",
                        "description": "If true, only applies to on-time deliveries. Default false.",
                    },
                    "allocation": {
                        "type": "number",
                        "description": "Ministry budget allocation for this rule. Default 0.",
                    },
                    "cargo_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of cargo type keys this rule applies to. Empty = ALL cargos.",
                    },
                    "source_area_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of source area names. Empty = any source.",
                    },
                    "destination_area_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of destination area names. Empty = any destination.",
                    },
                },
                "required": ["name", "reward_type", "reward_value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_subsidy_rule_update",
            "description": "Update fields on an existing subsidy rule. Only provided fields are changed; omitted fields keep their current value.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rule_id": {
                        "type": "integer",
                        "description": "The ID of the rule to update",
                    },
                    "name": {"type": "string"},
                    "active": {"type": "boolean"},
                    "priority": {"type": "integer"},
                    "reward_type": {
                        "type": "string",
                        "enum": ["PERCENTAGE", "FLAT"],
                    },
                    "reward_value": {"type": "number"},
                    "scales_with_damage": {"type": "boolean"},
                    "requires_on_time": {"type": "boolean"},
                    "allocation": {"type": "number"},
                    "cargo_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "source_area_names": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "destination_area_names": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["rule_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_subsidy_rule_deactivate",
            "description": "Deactivate a subsidy rule (soft-disable). The rule is not deleted and can be reactivated later.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rule_id": {
                        "type": "integer",
                        "description": "The ID of the rule to deactivate",
                    },
                },
                "required": ["rule_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_subsidy_rule_reorder",
            "description": "Change the priority ordering of subsidy rules. The first ID in the list gets the highest priority.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ordered_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of rule IDs in desired priority order (first = highest priority)",
                    },
                },
                "required": ["ordered_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_job_config_get",
            "description": "Get the current server-wide job posting configuration (adaptive multiplier, treasury params, posting rate).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_job_config_update",
            "description": "Update one or more job posting configuration fields. Only provided fields are changed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_success_rate": {
                        "type": "number",
                        "description": "Target job completion rate (0.0-1.0)",
                    },
                    "min_multiplier": {
                        "type": "number",
                        "description": "Minimum adaptive multiplier",
                    },
                    "max_multiplier": {
                        "type": "number",
                        "description": "Maximum adaptive multiplier",
                    },
                    "players_per_job": {
                        "type": "integer",
                        "description": "Players per job (legacy, usually left at 10)",
                    },
                    "min_base_jobs": {
                        "type": "integer",
                        "description": "Base offset for log2 job count curve",
                    },
                    "posting_rate_multiplier": {
                        "type": "number",
                        "description": "Global multiplier on posting chance (0.5 = half rate, 2.0 = double)",
                    },
                    "treasury_equilibrium": {
                        "type": "integer",
                        "description": "Treasury balance at which spending is 'normal' (multiplier = 1.0)",
                    },
                    "treasury_sensitivity": {
                        "type": "number",
                        "description": "How aggressively spending changes with treasury balance",
                    },
                    "treasury_cap_ratio": {
                        "type": "number",
                        "description": "Ratio at which above-equilibrium multiplier reaches 2.0",
                    },
                    "max_posts_per_tick": {
                        "type": "integer",
                        "description": "Max new jobs per cron tick",
                    },
                },
                "required": [],
            },
        },
    },
]


class EconomyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _is_financial_minister(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator:
            return True
        return any(r.id == FINANCIAL_MINISTER_ROLE_ID for r in member.roles)

    def get_tool_definitions(self) -> list[dict]:
        return TOOL_DEFINITIONS

    async def execute_tool(
        self,
        function_name: str,
        arguments: dict,
        interaction: discord.Interaction | None,
    ) -> str:
        if (
            not interaction
            or not isinstance(interaction.user, discord.Member)
            or not self._is_financial_minister(interaction.user)
        ):
            return "Error: You need the Financial Minister role to manage economy settings."

        try:
            if function_name == "manage_subsidy_rules_list":
                return await self._list_rules()
            elif function_name == "manage_subsidy_rule_create":
                return await self._create_rule(arguments, interaction.user)
            elif function_name == "manage_subsidy_rule_update":
                return await self._update_rule(arguments, interaction.user)
            elif function_name == "manage_subsidy_rule_deactivate":
                return await self._deactivate_rule(arguments, interaction.user)
            elif function_name == "manage_subsidy_rule_reorder":
                return await self._reorder_rules(arguments, interaction.user)
            elif function_name == "manage_job_config_get":
                return await self._get_job_config()
            elif function_name == "manage_job_config_update":
                return await self._update_job_config(arguments, interaction.user)
            else:
                return json.dumps({"error": f"Unknown economy tool: {function_name}"})
        except Exception as e:
            log.error(f"Economy tool error ({function_name}): {e}", exc_info=True)
            return json.dumps({"error": f"Economy tool failed: {e}"})

    # ── Backend API client ─────────────────────────────────────────────

    async def _api_get(self, path: str) -> dict:
        url = f"{BACKEND_API_URL}/api/economy{path}"
        async with self.bot.http_session.get(url) as resp:
            return await resp.json()

    async def _api_post(self, path: str, data: dict) -> tuple[int, dict]:
        url = f"{BACKEND_API_URL}/api/economy{path}"
        async with self.bot.http_session.post(url, json=data) as resp:
            return resp.status, await resp.json()

    async def _api_patch(self, path: str, data: dict) -> tuple[int, dict]:
        url = f"{BACKEND_API_URL}/api/economy{path}"
        async with self.bot.http_session.patch(url, json=data) as resp:
            return resp.status, await resp.json()

    # ── Tool handlers ──────────────────────────────────────────────────

    async def _list_rules(self) -> str:
        rules = await self._api_get("/subsidy-rules/")
        if not isinstance(rules, list):
            return json.dumps(rules)
        return json.dumps(rules, indent=2)

    async def _create_rule(self, args: dict, user: discord.Member) -> str:
        status, data = await self._api_post("/subsidy-rules/", args)
        if status != 201:
            return json.dumps(data)

        await self._audit_log(
            "Subsidy Rule Created",
            user,
            self._format_rule_summary(data),
        )
        return json.dumps(data, indent=2)

    async def _update_rule(self, args: dict, user: discord.Member) -> str:
        rule_id = args.pop("rule_id")
        status, data = await self._api_patch(
            f"/subsidy-rules/{rule_id}/", args
        )
        if status != 200:
            return json.dumps(data)

        changes = {k: v for k, v in args.items() if v is not None}
        await self._audit_log(
            "Subsidy Rule Updated",
            user,
            f"Rule #{rule_id} ({data.get('name', '?')})\n"
            + "\n".join(f"**{k}**: {v}" for k, v in changes.items()),
        )
        return json.dumps(data, indent=2)

    async def _deactivate_rule(self, args: dict, user: discord.Member) -> str:
        rule_id = args["rule_id"]
        status, data = await self._api_post(
            f"/subsidy-rules/{rule_id}/deactivate/", {}
        )
        if status != 200:
            return json.dumps(data)

        await self._audit_log(
            "Subsidy Rule Deactivated",
            user,
            f"Rule #{rule_id} ({data.get('name', '?')})",
        )
        return json.dumps(data, indent=2)

    async def _reorder_rules(self, args: dict, user: discord.Member) -> str:
        status, data = await self._api_post("/subsidy-rules/reorder/", args)
        if status != 200:
            return json.dumps(data)

        await self._audit_log(
            "Subsidy Rules Reordered",
            user,
            f"New order: {args['ordered_ids']}",
        )
        return json.dumps(data, indent=2)

    async def _get_job_config(self) -> str:
        data = await self._api_get("/job-config/")
        return json.dumps(data, indent=2)

    async def _update_job_config(self, args: dict, user: discord.Member) -> str:
        status, data = await self._api_patch("/job-config/", args)
        if status != 200:
            return json.dumps(data)

        changes = {k: v for k, v in args.items() if v is not None}
        await self._audit_log(
            "Job Config Updated",
            user,
            "\n".join(f"**{k}**: {v}" for k, v in changes.items()),
        )
        return json.dumps(data, indent=2)

    # ── Audit logging ──────────────────────────────────────────────────

    def _format_rule_summary(self, rule: dict) -> str:
        lines = [
            f"**{rule['name']}** (ID: {rule['id']})",
            f"Reward: {rule['reward_type']} {rule['reward_value']}",
            f"Priority: {rule['priority']}",
        ]
        if rule.get("cargo_keys"):
            lines.append(f"Cargos: {', '.join(rule['cargo_keys'])}")
        if rule.get("source_area_names"):
            lines.append(f"Source areas: {', '.join(rule['source_area_names'])}")
        if rule.get("destination_area_names"):
            lines.append(f"Dest areas: {', '.join(rule['destination_area_names'])}")
        return "\n".join(lines)

    async def _audit_log(self, action: str, user: discord.Member, details: str):
        if not ECONOMY_AUDIT_CHANNEL_ID:
            return
        channel = self.bot.get_channel(ECONOMY_AUDIT_CHANNEL_ID)
        if not channel:
            log.warning(f"Economy audit channel {ECONOMY_AUDIT_CHANNEL_ID} not found")
            return
        embed = discord.Embed(
            title=f"Economy: {action}",
            description=details,
            color=discord.Color.gold(),
            timestamp=datetime.now(tz=UTC),
        )
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        try:
            await channel.send(embed=embed)
        except Exception as e:
            log.warning(f"Failed to send economy audit log: {e}")
