import os
import yaml
import re
from typing import List, Dict, Any, Optional

class SOPStore:
    def __init__(self, base_dir: str = "."):
        self.base_dir = os.path.abspath(base_dir)

    def _parse_frontmatter(self, file_content: str) -> Optional[Dict[str, Any]]:
        """Parses the YAML frontmatter from a SKILL.md file."""
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", file_content, re.DOTALL | re.MULTILINE)
        if not match:
            return None
        try:
            return yaml.safe_load(match.group(1))
        except Exception as e:
            # If parsing fails, skip or log
            return None

    def scan_skills(self) -> List[Dict[str, Any]]:
        """Scans the base directory for skills containing SKILL.md and parses metadata."""
        skills = []
        if not os.path.exists(self.base_dir):
            return skills

        for entry in os.listdir(self.base_dir):
            entry_path = os.path.join(self.base_dir, entry)
            if os.path.isdir(entry_path):
                skill_md_path = os.path.join(entry_path, "SKILL.md")
                if os.path.exists(skill_md_path):
                    try:
                        with open(skill_md_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        
                        metadata = self._parse_frontmatter(content)
                        if metadata:
                            # Verify if workflow.yaml exists
                            workflow_path = os.path.join(entry_path, "assets", "workflow.yaml")
                            has_workflow = os.path.exists(workflow_path)
                            
                            skills.append({
                                "name": metadata.get("name", entry),
                                "description": metadata.get("description", ""),
                                "allowed_tools": metadata.get("allowed-tools", []),
                                "directory": entry_path,
                                "skill_md_path": skill_md_path,
                                "workflow_path": workflow_path if has_workflow else None,
                                "raw_content": content
                            })
                    except Exception as e:
                        # Log error or ignore corrupted files
                        pass
        return skills

    def search(self, query: str, agent_capabilities: List[str]) -> List[Dict[str, Any]]:
        """
        Searches and filters SOPs based on:
        1. Query relevance (simple keyword overlap score on name & description).
        2. Capability check (the agent must have all capabilities listed in the skill's allowed_tools).
        """
        all_skills = self.scan_skills()
        matching_skills = []

        # Convert query to lowercase words for search
        query_words = set(re.findall(r"\w+", query.lower()))

        for skill in all_skills:
            # 1. Capability Filtering
            required_tools = skill.get("allowed_tools", [])
            # The agent must have all the tools required by the SOP to execute it
            has_capabilities = all(tool in agent_capabilities for tool in required_tools)
            
            if not has_capabilities:
                continue

            # 2. Score relevance (Simple word match overlap)
            name_text = skill.get("name", "").lower()
            desc_text = skill.get("description", "").lower()
            
            score = 0
            for word in query_words:
                if word in name_text:
                    score += 5  # Higher weight for title/name match
                if word in desc_text:
                    score += 2  # Lower weight for description match
            
            # If there's any match or query is empty (returns all matching capability SOPs)
            if score > 0 or not query_words:
                skill_copy = dict(skill)
                skill_copy["search_score"] = score
                matching_skills.append(skill_copy)

        # Sort by score descending
        matching_skills.sort(key=lambda x: x["search_score"], reverse=True)
        return matching_skills
