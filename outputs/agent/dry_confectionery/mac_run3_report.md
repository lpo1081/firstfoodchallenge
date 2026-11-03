마무리 단계 완료 (10:50–11:00 KST, API 비용 0, 에러 없음)

■ 반영
- 백업: ~/kfood_scout_backup_agent3_202611031050.tgz
- v2 파일 5개(loop.py, scout.py, run_rolling.py, test_agent.py, config/studies/agent_vs_base.yaml)를 같은 경로에 두었고 MANIFEST2 sha256 5개 모두 OK
- pytest -q tests: 13 passed
- 이전 k_export_agent.yaml(1차, 깨진 데이터 버전)은 data/k_export_agent.v1.yaml.bak로 보관한 뒤 adopt로 재생성

■ adopt 결과 (고친 구글 트렌드 기준)
- 추가: kpop_interest, kfood_interest, korea_visitors_pc, learn_korean_interest (kculture 최신 판정 = log 기준 단독 accepted·weak 지표. kpop_interest_change는 log 단독 기각이라 제외)
- 제거(평균 가중치 0.03 미만): import_market_cagr(0.028), korea_share(0.025)
- 기존 k_export 대비 표본 밖: 평균 +0.118, 우위 100%, 90% 구간 +0.064 ~ +0.167 (7개 구간 모두 개선, 최소 +0.006(2013→16), 최대 +0.230(2017→20))
- written: true

adopt.json 전문:
{"added":["kpop_interest","kfood_interest","korea_visitors_pc","learn_korean_interest"],"dropped":["import_market_cagr","korea_share"],"mean_weights":{"import_market_size":0.18,"import_market_cagr":0.028,"hh_consumption_pc_cagr":0.037,"population_size":0.064,"youth_share":0.035,"urbanization_change":0.049,"gdp_pc_ppp":0.095,"import_pc_cagr":0.036,"korea_exports_size":0.053,"korea_exports_cagr":0.04,"korea_share":0.025,"korea_share_change":0.05,"kpop_interest":0.068,"kfood_interest":0.12,"korea_visitors_pc":0.07,"learn_korean_interest":0.05},"oos_vs_base":{"mean_delta":0.11842857142857144,"p_better":1.0,"ci90":[0.06380270166002437,0.16680243273490897]},"oos_pairs":[{"fit":2012,"test":2015,"n":54,"base":0.191,"aug":0.3,"delta":0.109},{"fit":2013,"test":2016,"n":50,"base":0.286,"aug":0.292,"delta":0.006},{"fit":2014,"test":2017,"n":50,"base":0.245,"aug":0.359,"delta":0.114},{"fit":2015,"test":2018,"n":55,"base":0.488,"aug":0.605,"delta":0.117},{"fit":2016,"test":2019,"n":54,"base":0.499,"aug":0.611,"delta":0.111},{"fit":2017,"test":2020,"n":57,"base":0.267,"aug":0.497,"delta":0.23},{"fit":2018,"test":2021,"n":57,"base":0.352,"aug":0.494,"delta":0.142}],"written":true}
(원본 파일은 indent=1 들여쓰기 형식이고 내용은 같음. adopt 콘솔 출력은 이 JSON 한 줄)

■ 새 k_export_agent.yaml 지표 14개 (id | series/flow | transform | group)
import_market_size | M | level_log | 성장성
hh_consumption_pc_cagr | NE.CON.PRVT.PC.KD | cagr | 성장성
population_size | SP.POP.TOTL | level_log | 성장성
youth_share | SP.POP.0014.TO.ZS | level | 소비트렌드
urbanization_change | SP.URB.TOTL.IN.ZS | diff | 소비트렌드
gdp_pc_ppp | NY.GDP.PCAP.PP.KD | level_log | 소비트렌드
import_pc_cagr | M | per_capita_cagr | 소비트렌드
korea_exports_size | KOR_X | level_log | 수출입
korea_exports_cagr | KOR_X | cagr | 수출입
korea_share_change | KOR_X | share_diff | 수출입
kpop_interest | gtrends_kpop | level | 소비트렌드
kfood_interest | gtrends_kfood | level | 소비트렌드
korea_visitors_pc | kto_visitors | per_capita | 소비트렌드
learn_korean_interest | gtrends_learnkorean | level | 소비트렌드

■ study 콘솔 출력 전체 (python -m kfood_scout study --study agent_vs_base)
[study] category=dry_confectionery__criterion=k_export__method=rolling: 계산
[study] category=dry_confectionery__criterion=k_export_agent__method=rolling: 계산
category=dry_confectionery__criterion=k_export__method=rolling n_windows= [53, 54, 55, 57] group_trend= {'성장성': -0.249, '소비트렌드': 0.277, '수출입': -0.027} XX_groups= {'성장성': 0.189, '소비트렌드': 0.519, '수출입': 0.293} oos_X_prev= 0.33886803916595376 top5_new_XX= ['Indonesia', 'Philippines', 'Thailand', 'Mongolia', 'Mexico'] forecast_rank_corr= 0.9999999999999998 top10_overlap= 10
category=dry_confectionery__criterion=k_export_agent__method=rolling n_windows= [54, 54, 56, 58] group_trend= {'성장성': -0.191, '소비트렌드': 0.145, '수출입': 0.048} XX_groups= {'성장성': 0.137, '소비트렌드': 0.659, '수출입': 0.204} oos_X_prev= 0.45853733414617864 top5_new_XX= ['Indonesia', 'Philippines', 'Mongolia', 'Thailand', 'Canada'] forecast_rank_corr= 0.8952077921137572 top10_overlap= 8
(portfolio가 없는 study라 '통합 TOP10' 줄은 출력되지 않음)

■ 나란히 비교 (k_export → k_export_agent)
창별 그룹 비중 (2012 / 2015 / 2018 / 2021):
- 성장성: 0.529 / 0.659 / 0.487 / 0.280 → 0.399 / 0.439 / 0.250 / 0.208
- 소비트렌드: 0.154 / 0.215 / 0.272 / 0.431 → 0.460 / 0.472 / 0.617 / 0.605
- 수출입: 0.317 / 0.126 / 0.242 / 0.290 → 0.139 / 0.090 / 0.131 / 0.187
XX 그룹 비중: 성장성 0.189, 소비트렌드 0.519, 수출입 0.293 → 성장성 0.137, 소비트렌드 0.659, 수출입 0.204
창 내 적합 rho: 0.573 / 0.279 / 0.571 / 0.515 → 0.673 / 0.324 / 0.673 / 0.557
표본 밖 X_prev 평균: 0.339 → 0.459 (모멘텀 단독 0.041 → 0.037)
XX 가중치 상위(agent): urbanization_change 0.184, kpop_interest 0.141, kfood_interest 0.103, gdp_pc_ppp 0.102. korea_visitors_pc(0.011)와 learn_korean_interest(0.009)는 추세 외삽 후 거의 0
2024→27 신규(기진출 제외) 유망국 상위 10
- k_export: 인도네시아, 필리핀, 태국, 몽골, 멕시코, 네덜란드, 나이지리아, 말레이시아, 페루, 캐나다
- k_export_agent: 인도네시아 78.3, 필리핀 77.1, 몽골 73.0, 태국 68.4, 캐나다 67.7, 말레이시아 67.2, 멕시코 66.8, 미국 63.5, 네덜란드 63.4, 캄보디아 62.2
- 기존 기준 대비: 예측 순위 상관 0.895, TOP10 겹침 8개(나이지리아·페루가 빠지고 미국·캄보디아가 들어옴), XX 가중치 상관 0.617, 그룹 추세 방향은 성장성·소비트렌드 같음, 수출입 다름
→ TOP3(기진출 제외): 두 기준 모두 인도네시아·필리핀이 1·2위이고, 3위가 태국(기존)에서 몽골(에이전트)로 바뀝니다.

■ run_rolling.py 2024 k_export_agent 확인 결과 (예상대로 외부 지표가 빠짐)
data/panel_dry_confectionery.csv에 EX:* 시리즈가 없어서 raw_now의 kpop·kfood·방한객·한국어학습 값이 60개국 전부 null이고, 백분위가 모두 50.0(고유값 1개)입니다. 그런데도 롤링 적합은 상수 열에 가중치를 나눠 주므로(2021 창 소비트렌드 0.619 등) 수치가 study 결과와 다릅니다(표본 밖 X_prev 0.173 / 0.503 / 0.376, TOP10은 기존 k_export와 거의 같음). 이 비교에는 study 결과를 써야 합니다. 출력 파일: outputs/dry_confectionery__k_export_agent/rolling.json

■ outputs/studies/agent_vs_base/comparison.json 전문 (공백만 뺀 compact. 원본 23,718바이트)
