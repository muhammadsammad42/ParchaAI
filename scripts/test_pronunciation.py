
import sys
import asyncio
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from parcha_ai_backend.pronunciation import (
    resolve_pronunciation,
    get_pronunciation_stats,
    _cache_path,
    _load_cache,
)
from parcha_ai_backend.urdu_explanation import UrduExplainer
from parcha_ai_backend.validation import MedicineDetail


def test_manual_dict_hits():
    """Test 1: Manual dictionary hits return expected output."""
    print("\n" + "="*70)
    print("TEST 1: Manual Dictionary Hits")
    print("="*70)
    
    test_cases = [
        ("Augmentin", "اگمینٹن"),
        ("Paracetamol", "پیراسیٹامول"),
        ("Azithromycin", "ازیتھرومائسن"),
        ("Ibuprofen", "آئبوپروفین"),
        ("Aspirin", "اسپرین"),
    ]
    
    passed = 0
    failed = 0
    
    for english, expected_urdu in test_cases:
        try:
            result = resolve_pronunciation(english)
            if result == expected_urdu:
                print(f"PASS: {english} -> {result}")
                passed += 1
            else:
                print(f"FAIL: {english} -> {result} (expected: {expected_urdu})")
                failed += 1
        except Exception as e:
            print(f"ERROR: {english} -> {e}")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_g2p_fallback():
    """Test 2: G2P fallback on unseen brand names."""
    print("\n" + "="*70)
    print("TEST 2: G2P Fallback (Unseen Brand Names)")
    print("="*70)
    
    unseen_names = [
        "Brufen",        
        "Flagyl",        
        "Norflox",       
        "Risek",         
        "Surbex",        
    ]
    
    passed = 0
    failed = 0
    
    for medicine_name in unseen_names:
        try:
            result = resolve_pronunciation(medicine_name)
            
            is_valid = (
                result and
                len(result) >= 2 and
                any('\u0600' <= c <= '\u06FF' for c in result)
            )
            
            if is_valid:
                print(f"PASS: {medicine_name} -> {result} (source: G2P or LLM)")
                passed += 1
            else:
                print(f"FAIL: {medicine_name} -> {result} (invalid Urdu)")
                failed += 1
        except Exception as e:
            print(f"ERROR: {medicine_name} -> {e}")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    print("\nNOTE: Check cache/pronunciation_review.log for tier 2/3 entries")
    return failed == 0


def test_cache_round_trip():
    """Test 3: Cache read/write round-trips correctly."""
    print("\n" + "="*70)
    print("TEST 3: Cache Read/Write Round-Trip")
    print("="*70)
    
    # Resolve a few medicines to populate cache
    test_medicines = ["Augmentin", "Paracetamol", "Brufen"]
    
    print("\nResolving medicines to populate cache...")
    for med in test_medicines:
        result = resolve_pronunciation(med)
        print(f"  {med} -> {result}")
    
    # Check cache file exists
    if not _cache_path.exists():
        print(f"\n✗ FAIL: Cache file not created at {_cache_path}")
        return False
    
    print(f"\n✓ Cache file exists: {_cache_path}")
    
    # Load cache and verify entries
    cache = _load_cache()
    
    if "pronunciations" not in cache:
        print("FAIL: Cache missing 'pronunciations' key")
        return False
    
    cached_count = len(cache["pronunciations"])
    print(f"Cache contains {cached_count} entries")
    
    # Verify each test medicine is in cache
    missing = []
    for med in test_medicines:
        if med not in cache["pronunciations"]:
            missing.append(med)
    
    if missing:
        print(f"FAIL: Missing from cache: {missing}")
        return False
    
    print(f"All {len(test_medicines)} test medicines found in cache")
    
    # Verify cache structure
    for med in test_medicines:
        entry = cache["pronunciations"][med]
        required_fields = ["urdu", "source", "timestamp"]
        
        for field in required_fields:
            if field not in entry:
                print(f"FAIL: Cache entry for {med} missing field: {field}")
                return False
    
    print("All cache entries have required fields (urdu, source, timestamp)")
    
    # Show stats
    stats = get_pronunciation_stats()
    print(f"\nCache statistics:")
    print(f"Total: {stats['total']}")
    print(f"Manual dict: {stats['manual_dict']}")
    print(f"G2P: {stats['g2p']}")
    print(f"LLM: {stats['llm']}")
    
    return True


async def test_display_vs_speech_text():
    """Test 4: display_text ≠ speech_text for same medicine."""
    print("\n" + "="*70)
    print("TEST 4: Display Text vs Speech Text Difference")
    print("="*70)
    
    # Create a test medicine
    test_med = MedicineDetail(
        medicine_name="Augmentin",
        dosage="625mg",
        frequency="1-0-1",
        duration="5 days",
        purpose="bacterial infection",
        confidence=0.95,
    )
    
    # Generate Urdu explanation
    explainer = UrduExplainer()
    
    try:
        urdu_text = await explainer.explain(test_med, position=0)
        print(f"\nGenerated Urdu text:")
        print(f"  {urdu_text}")
        
        # Get pronunciation
        urdu_name = resolve_pronunciation(test_med.medicine_name)
        print(f"\nResolved pronunciation: {test_med.medicine_name} → {urdu_name}")
        
        # speech_text = pure Urdu
        speech_text = urdu_text
        
        # display_text = English (Urdu) format
        display_text = urdu_text.replace(urdu_name, f"{test_med.medicine_name} ({urdu_name})", 1)
        
        print(f"\nspeech_text (for TTS):")
        print(f"  {speech_text}")
        
        print(f"\ndisplay_text (for UI):")
        print(f"  {display_text}")
        
        # Verify they're different
        if speech_text == display_text:
            print("\n✗ FAIL: speech_text and display_text are identical")
            return False
        
        # Verify display_text contains English name
        if test_med.medicine_name not in display_text:
            print(f"\n✗ FAIL: display_text doesn't contain English name '{test_med.medicine_name}'")
            return False
        
        # Verify display_text contains parentheses (format marker)
        if "(" not in display_text or ")" not in display_text:
            print("\nFAIL: display_text doesn't contain parentheses (expected format: 'English (Urdu)')")
            return False
        
        print("\nPASS: display_text ≠ speech_text")
        print("PASS: display_text contains English name")
        print("PASS: display_text uses 'English (Urdu)' format")
        
        return True
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("PRONUNCIATION PIPELINE TEST SUITE")
    print("="*70)
    
    results = {}
    
    # Test 1: Manual dictionary hits
    results["manual_dict"] = test_manual_dict_hits()
    
    # Test 2: G2P fallback
    results["g2p_fallback"] = test_g2p_fallback()
    
    # Test 3: Cache round-trip
    results["cache_round_trip"] = test_cache_round_trip()
    
    # Test 4: Display vs speech text (async)
    results["display_vs_speech"] = asyncio.run(test_display_vs_speech_text())
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed
    
    for test_name, result in results.items():
        status = "PASS" if result else "FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if failed > 0:
        print(f"\n {failed} test(s) failed. Review output above.")
        sys.exit(1)
    else:
        print("\nAll tests passed!")
        print("\nNEXT STEPS:")
        print("1. Review cache/pronunciation_review.log for tier 2/3 entries")
        print("2. Verify Urdu pronunciations with native speaker")
        print("3. Test on real prescription images")
        sys.exit(0)


if __name__ == "__main__":
    main()
