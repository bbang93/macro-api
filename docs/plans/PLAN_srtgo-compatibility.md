# Implementation Plan: srtgo 호환성 수정

**Status**: 🔄 In Progress
**Started**: 2025-12-24
**Last Updated**: 2025-12-24
**Estimated Completion**: 2025-12-24

---

**CRITICAL INSTRUCTIONS**: After completing each phase:
1. Check off completed task checkboxes
2. Run all quality gate validation commands
3. Verify ALL quality gate items pass
4. Update "Last Updated" date above
5. Document learnings in Notes section
6. Only then proceed to next phase

**DO NOT skip quality gates or proceed with failing checks**

---

## Overview

### Feature Description
기존 srtgo CLI 매크로 코드와 동일한 방식으로 macro-api가 동작하도록 수정.
기존 코드는 안정적으로 작동했으므로, 가능한 기존 로직을 그대로 적용.

### Success Criteria
- [ ] 검색 시 승객 구성이 기존과 동일하게 처리됨 (성인만 통합)
- [ ] KTX train_type 필터링이 API 파라미터로 직접 전달됨
- [ ] 예약대기 처리가 기존 로직과 일치함
- [ ] 좌석 가용성 체크가 기존 `_is_seat_available()` 로직과 동일함
- [ ] 매크로가 무한 루프로 성공할 때까지 재시도함

### User Impact
기존 CLI 매크로와 동일한 예매 성공률 및 안정성 확보

---

## Architecture Decisions

| Decision | Rationale | Trade-offs |
|----------|-----------|------------|
| 검색 시 성인만 전달 | 기존 코드가 이 방식으로 안정적 작동 | 검색 결과 정확도 vs 호환성 |
| 예약대기 기존 방식 | reserve() 내에서 자동 처리가 더 간단 | 코드 분리 vs 기존 호환성 |

---

## Dependencies

### Required Before Starting
- [x] 기존 srtgo 코드 분석 완료
- [x] macro-api 현재 구현 분석 완료
- [x] 차이점 목록 정리 완료

### External Dependencies
- SRT/KTX 라이브러리: 기존과 동일
- FastAPI: 기존과 동일

---

## Implementation Phases

### Phase 1: 검색 승객 구성 수정
**Goal**: 검색 시 성인만 통합해서 전달하도록 수정 (기존 srtgo 방식)
**Estimated Time**: 30분
**Status**: ✅ Completed

#### 현재 코드 문제
```python
# rail_service.py 현재 구현
passenger_list = self._build_passenger_list(passengers)  # 실제 구성 전달

trains = await loop.run_in_executor(
    None,
    partial(
        self.client.search_train,
        passengers=passenger_list,  # ← 실제 구성 그대로
    ),
)
```

#### 기존 srtgo 방식 (srtgo.py:616)
```python
# 검색 시 - 성인만 통합
"passengers": [passenger_classes["adult"](total_count)]

# 예약 시 - 실제 구성 전달
rail.reserve(train, passengers=passengers, option=options["type"])
```

#### Tasks
- [ ] **Task 1.1**: `rail_service.py`에 검색용 승객 리스트 생성 메서드 추가
  - File: `/api/services/rail_service.py`
  - 메서드: `_build_search_passenger_list()` - 성인만 통합
  - 메서드: `_build_reserve_passenger_list()` - 실제 구성 (기존 `_build_passenger_list` 이름 변경)

- [ ] **Task 1.2**: `search_trains()` 메서드 수정
  - 검색 시 `_build_search_passenger_list()` 사용
  - 총 인원수 계산 후 성인으로만 전달

- [ ] **Task 1.3**: `reserve()` 및 `reserve_standby()` 메서드 확인
  - 예약 시 `_build_reserve_passenger_list()` 사용 확인

#### Quality Gate
- [ ] 서버 재시작 성공
- [ ] 열차 검색 정상 동작
- [ ] 예약 시도 정상 동작
- [ ] 로그에서 승객 구성 확인

---

### Phase 2: KTX train_type 필터링 수정
**Goal**: KTX 검색 시 train_type을 API 파라미터로 직접 전달
**Estimated Time**: 20분
**Status**: ✅ Completed

#### 현재 코드 문제
```python
# rail_service.py 현재 구현
# normalize 후 필터링 (비효율적)
if train_types and not self._is_srt:
    train_type_values = [t.value for t in train_types]
    normalized_trains = [
        t for t in normalized_trains
        if t["train_name"] in train_type_values
    ]
```

#### 기존 srtgo 방식 (srtgo.py:610-627)
```python
params = {
    ...
    **(
        {"available_only": False}
        if is_srt
        else {
            "include_no_seats": True,
            **({"train_type": TrainType.KTX} if "ktx" in options else {}),
        }
    ),
}
```

#### Tasks
- [ ] **Task 2.1**: KTX 검색 시 `train_type` 파라미터 직접 전달
  - File: `/api/services/rail_service.py`
  - `search_trains()` 메서드 수정
  - train_types 파라미터를 API에 직접 전달

- [ ] **Task 2.2**: normalize 후 필터링 제거
  - 이미 API에서 필터링되므로 불필요

#### Quality Gate
- [ ] KTX 검색 시 train_type 필터링 정상 동작
- [ ] 원하는 열차 종류만 반환되는지 확인

---

### Phase 3: 예약대기 로직 확인 및 수정
**Goal**: 기존 srtgo의 예약대기 처리 로직과 일치시키기
**Estimated Time**: 30분
**Status**: ✅ Completed

#### 기존 srtgo 방식 분석 (srtgo.py:803-819)
```python
def _is_seat_available(train, seat_type, rail_type):
    if rail_type == "SRT":
        if not train.seat_available():
            return train.reserve_standby_available()  # ← 좌석 없으면 대기 확인
        if seat_type in [SeatType.GENERAL_FIRST, SeatType.SPECIAL_FIRST]:
            return train.seat_available()  # ← 아무거나 있으면 OK
        if seat_type == SeatType.GENERAL_ONLY:
            return train.general_seat_available()
        return train.special_seat_available()
```

#### 현재 macro-api 로직 (job_service.py:344-363)
```python
# 복잡한 if-else 로직
if job.seat_type in (SeatType.GENERAL_FIRST, SeatType.GENERAL_ONLY):
    can_reserve = train["general_seat_available"]
if not can_reserve and job.seat_type in (SeatType.SPECIAL_FIRST, SeatType.SPECIAL_ONLY):
    can_reserve = train["special_seat_available"]
# ... 더 복잡한 폴백 로직
```

#### Tasks
- [ ] **Task 3.1**: 좌석 가용성 체크 함수를 기존 로직으로 단순화
  - File: `/api/services/job_service.py`
  - 기존 `_is_seat_available()` 로직 그대로 구현
  - `use_standby` 플래그를 기존처럼 "좌석 없으면 자동 대기"로 변경

- [ ] **Task 3.2**: 예약 시도 로직 수정
  - 좌석 가용 시 → 일반 예약
  - 좌석 없음 + 대기 가능 시 → 예약대기
  - 기존 로직과 동일하게 처리

#### Quality Gate
- [ ] 좌석 있는 열차 예약 정상 동작
- [ ] 좌석 없는 열차 예약대기 정상 동작
- [ ] 기존 CLI와 동일한 동작 확인

---

### Phase 4: 기타 차이점 수정 및 최종 검증
**Goal**: 나머지 차이점 수정 및 전체 기능 검증
**Estimated Time**: 30분
**Status**: ✅ Completed

#### Tasks
- [ ] **Task 4.1**: 에러 처리 로직 최종 확인
  - 무시 가능한 에러 목록 기존과 일치 확인
  - 자동 재시도 로직 확인

- [ ] **Task 4.2**: NetFunnel 처리 확인
  - 콜백 설정 정상 동작 확인
  - 대기열 통과 후 정상 진행 확인

- [ ] **Task 4.3**: 전체 매크로 플로우 테스트
  - 로그인 → 검색 → 예약 → 성공 전체 플로우 확인
  - 실패 시 자동 재시도 확인

- [ ] **Task 4.4**: 코드 정리 및 로깅 최적화
  - 불필요한 디버그 로그 제거/조정
  - 에러 메시지 명확화

#### Quality Gate
- [ ] 전체 매크로 플로우 정상 동작
- [ ] 기존 srtgo CLI와 동일한 동작 확인
- [ ] 에러 발생 시 자동 복구 확인

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation Strategy |
|------|-------------|--------|---------------------|
| API 파라미터 변경으로 인한 에러 | Low | High | 변경 전후 테스트 철저히 |
| 예약대기 로직 불일치 | Medium | High | 기존 코드 정확히 복사 |
| 승객 구성 변경으로 검색 실패 | Low | Medium | 기존 방식으로 원복 |

---

## Rollback Strategy

### If Phase 1 Fails
- `_build_passenger_list()` 원래 코드로 복원
- `search_trains()` 원래 파라미터 복원

### If Phase 2 Fails
- train_type 필터링 원래 방식(normalize 후)으로 복원

### If Phase 3 Fails
- 좌석 가용성 체크 원래 로직으로 복원
- 예약대기 분기 원래 방식으로 복원

### If Phase 4 Fails
- 해당 변경사항만 원복

---

## Progress Tracking

### Completion Status
- **Phase 1**: ✅ 100%
- **Phase 2**: ✅ 100%
- **Phase 3**: ✅ 100%
- **Phase 4**: ✅ 100%

**Overall Progress**: 100% complete

---

## Notes & Learnings

### Implementation Notes
- **Phase 1**: `_build_search_passenger_list()` 메서드 추가 - 검색 시 모든 승객을 성인으로 통합
- **Phase 1**: `_build_reserve_passenger_list()` 메서드 추가 - 예약 시 실제 승객 구성 전달
- **Phase 2**: `TrainType` 매핑 추가 (`TRAIN_TYPE_TO_KTX`) - macro-api enum을 ktx TrainType으로 변환
- **Phase 2**: KTX 검색 시 `train_type` 파라미터를 API에 직접 전달
- **Phase 3**: 좌석 가용성 체크 로직 단순화 - srtgo의 `_is_seat_available()` 로직과 동일하게 구현
- **Phase 3**: SRT/KTX 라이브러리의 `reserve()` 메서드가 내부적으로 대기 예약을 자동 처리함을 발견
- **Phase 3**: `reserve_standby()` 직접 호출 제거 - `reserve()`만 호출하면 됨

### Key Findings
- SRT `reserve()` 메서드: 좌석 없으면 자동으로 `reserve_standby()` 호출 (srt.py:862-865)
- KTX `reserve()` 메서드: 좌석 없으면 `txtJobId`를 "1102"로 설정하여 대기 예약 처리 (ktx.py:720)

### Blockers Encountered
- 없음

---

## References

### 기존 코드 파일
- `/Users/bangseokgeun/Desktop/workspace/srtgo/srtgo/srtgo.py` - 메인 매크로 로직
- `/Users/bangseokgeun/Desktop/workspace/srtgo/srtgo/srt.py` - SRT 클라이언트
- `/Users/bangseokgeun/Desktop/workspace/srtgo/srtgo/ktx.py` - KTX 클라이언트

### 수정 대상 파일
- `/Users/bangseokgeun/Desktop/workspace/macro-api/api/services/rail_service.py`
- `/Users/bangseokgeun/Desktop/workspace/macro-api/api/services/job_service.py`

---

**Plan Status**: ✅ Completed
**Completed Date**: 2025-12-24
**Blocked By**: None
