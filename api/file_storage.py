"""
File-Based Persistence Layer for Self-Hosted Deployments

Provides JSON file storage as an alternative to Redis/Vercel KV.
Automatically used when KV_REST_API_URL is not configured.

Storage structure:
- data/claims.json - Active hit claims
- data/yata_cache.json - YATA battle stats estimates
- data/faction_profiles.json - Faction member profiles
- data/leaderboards.json - User statistics for leaderboards
"""

import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Optional, List, Dict


class FileStorage:
    """
    Thread-safe file-based key-value storage.
    Used as fallback when Redis/Vercel KV is not available.
    """

    def __init__(self, storage_dir: str = "data"):
        """
        Initialize file storage.
        
        Args:
            storage_dir: Directory to store JSON files (default: 'data/')
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
        self._locks: Dict[str, Lock] = {}
        self._global_lock = Lock()

    def _get_lock(self, namespace: str) -> Lock:
        """Get or create a lock for a specific namespace."""
        with self._global_lock:
            if namespace not in self._locks:
                self._locks[namespace] = Lock()
            return self._locks[namespace]

    def _get_file_path(self, namespace: str) -> Path:
        """Get file path for a namespace."""
        return self.storage_dir / f"{namespace}.json"

    def _load_namespace(self, namespace: str) -> Dict[str, Any]:
        """Load all data from a namespace file."""
        file_path = self._get_file_path(namespace)
        if not file_path.exists():
            return {}
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading {namespace}: {e}")
            return {}

    def _save_namespace(self, namespace: str, data: Dict[str, Any]) -> bool:
        """Save all data to a namespace file."""
        file_path = self._get_file_path(namespace)
        
        try:
            # Write to temp file first, then atomic rename
            temp_path = file_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Atomic replace
            temp_path.replace(file_path)
            return True
        except IOError as e:
            print(f"Error saving {namespace}: {e}")
            return False

    def get(self, namespace: str, key: str) -> Optional[Any]:
        """
        Get value from storage.
        
        Args:
            namespace: Storage namespace (e.g., 'claims', 'yata_cache')
            key: Key within namespace
            
        Returns:
            Value or None if not found
        """
        lock = self._get_lock(namespace)
        with lock:
            data = self._load_namespace(namespace)
            entry = data.get(key)
            
            if entry is None:
                return None
            
            # Check expiration if present
            if isinstance(entry, dict) and '_expires_at' in entry:
                if time.time() > entry['_expires_at']:
                    # Expired, remove it
                    del data[key]
                    self._save_namespace(namespace, data)
                    return None
                # Remove metadata before returning
                result = entry.copy()
                result.pop('_expires_at', None)
                return result
            
            return entry

    def set(self, namespace: str, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """
        Set value in storage.
        
        Args:
            namespace: Storage namespace
            key: Key within namespace
            value: Value to store (must be JSON serializable)
            ex: Expiration time in seconds (optional)
            
        Returns:
            True if successful
        """
        lock = self._get_lock(namespace)
        with lock:
            data = self._load_namespace(namespace)
            
            # Add expiration metadata if specified
            if ex is not None:
                if not isinstance(value, dict):
                    value = {'_value': value}
                value['_expires_at'] = time.time() + ex
            
            data[key] = value
            return self._save_namespace(namespace, data)

    def delete(self, namespace: str, key: str) -> bool:
        """
        Delete key from storage.
        
        Args:
            namespace: Storage namespace
            key: Key to delete
            
        Returns:
            True if key was deleted, False if not found
        """
        lock = self._get_lock(namespace)
        with lock:
            data = self._load_namespace(namespace)
            if key in data:
                del data[key]
                self._save_namespace(namespace, data)
                return True
            return False

    def keys(self, namespace: str, pattern: Optional[str] = None) -> List[str]:
        """
        Get all keys in namespace, optionally filtered by pattern.
        
        Args:
            namespace: Storage namespace
            pattern: Optional key prefix filter
            
        Returns:
            List of keys
        """
        lock = self._get_lock(namespace)
        with lock:
            data = self._load_namespace(namespace)
            
            # Remove expired entries
            now = time.time()
            expired = []
            for key, value in data.items():
                if isinstance(value, dict) and '_expires_at' in value:
                    if now > value['_expires_at']:
                        expired.append(key)
            
            for key in expired:
                del data[key]
            
            if expired:
                self._save_namespace(namespace, data)
            
            # Filter by pattern if specified
            if pattern:
                return [k for k in data.keys() if k.startswith(pattern)]
            return list(data.keys())

    def clear_namespace(self, namespace: str) -> bool:
        """
        Clear all data in a namespace.
        
        Args:
            namespace: Storage namespace to clear
            
        Returns:
            True if successful
        """
        lock = self._get_lock(namespace)
        with lock:
            return self._save_namespace(namespace, {})

    def get_all(self, namespace: str) -> Dict[str, Any]:
        """
        Get all key-value pairs in a namespace.
        Removes expired entries and metadata.
        
        Args:
            namespace: Storage namespace
            
        Returns:
            Dictionary of all non-expired entries
        """
        lock = self._get_lock(namespace)
        with lock:
            data = self._load_namespace(namespace)
            
            # Remove expired entries and clean metadata
            now = time.time()
            result = {}
            expired = []
            
            for key, value in data.items():
                if isinstance(value, dict) and '_expires_at' in value:
                    if now > value['_expires_at']:
                        expired.append(key)
                        continue
                    # Remove metadata
                    clean_value = value.copy()
                    clean_value.pop('_expires_at', None)
                    result[key] = clean_value
                else:
                    result[key] = value
            
            # Save if we removed expired entries
            if expired:
                for key in expired:
                    del data[key]
                self._save_namespace(namespace, data)
            
            return result

    def stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        stats = {
            'storage_dir': str(self.storage_dir),
            'namespaces': {},
        }
        
        for file_path in self.storage_dir.glob('*.json'):
            namespace = file_path.stem
            try:
                size = file_path.stat().st_size
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    stats['namespaces'][namespace] = {
                        'keys': len(data),
                        'size_bytes': size,
                    }
            except Exception:
                pass
        
        return stats


# Global instance
_file_storage: Optional[FileStorage] = None


def get_file_storage() -> FileStorage:
    """Get or create global file storage instance."""
    global _file_storage
    if _file_storage is None:
        _file_storage = FileStorage()
    return _file_storage


def is_self_hosted() -> bool:
    """
    Check if running in self-hosted mode (no Redis/Vercel KV).
    
    Returns:
        True if KV is not configured (use file storage)
    """
    kv_url = os.getenv("KV_REST_API_URL")
    kv_token = os.getenv("KV_REST_API_TOKEN")
    return not (kv_url and kv_token)
