from scripts.audit_priority_planning_layers import sample_point


def test_audit_uses_string_http_success_without_selecting_failures_or_other_regions():
    samples=[{'status':'200','point':[12,109],'z':13},
             {'status':403,'point':[12.1,109.1],'z':18},
             {'status':200,'point':[20,106],'z':19}]
    point,basis=sample_point(samples,[[11,108],[13,110]],[[11,108],[13,110]])
    assert point==[12,109]
    assert basis=='previous_positive_sample'


def test_island_does_not_reuse_mainland_focus_or_sample():
    point,basis=sample_point([{'status':200,'point':[10.6,107.3],'z':16}],
                            [[8.6,106.5],[8.8,106.7]],[[10,107],[11,108]])
    assert abs(point[0]-8.7)<1e-8
    assert abs(point[1]-106.6)<1e-8
    assert basis=='focus_midpoint_with_layer_membership'
